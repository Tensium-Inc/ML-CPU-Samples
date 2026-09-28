#!/usr/bin/env bash
# End-to-end verification INSIDE the built image. Not a stand-in: the real
# Dockerfile, the real daemon started by the real entrypoint as root, drivers
# run as the agent's uid, and tests/grade.py run as the verifier runs it.
#
# This exists because offline calibration cannot see a whole class of defect.
# `_private/calibrate.py` runs the service as an ordinary user, so every
# `geteuid() == 0` branch in the service is dead there -- including the one that
# demotes the candidate before executing it. That branch was broken for the
# entire life of the task and calibration still reported GREEN, because the
# permission it depends on only exists in the image. Anything privilege- or
# permission-shaped is only observable here.
#
#   usage: _private/verify_in_image.sh [scenario ...]     (default: all)
#
# Written for bash 3.2 (no associative arrays) so it runs on a stock mac.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASK="$(cd "$HERE/.." && pwd)"
IMAGE="funding-restatement-verify:local"

# name | driver | expected score | expected floor ("" = must score 1.0)
# A control that floors for the wrong reason has tested nothing, so the reason
# is asserted too, not just the number.
SCENARIOS='
gold|solution/solve.sh|1.0|
alt_correct|solution/alt_solve.sh|1.0|
alt2_correct|solution/alt2_solve.sh|1.0|
pc_iterating|_private/positive_controls/pc_iterating.sh|1.0|
nc_shipped|_private/negative_controls/nc_shipped_pipeline.sh|0.0|table
nc_restated_money|_private/negative_controls/nc_restated_money.sh|0.0|table
nc_cancelled|_private/negative_controls/nc_cancelled_undecided.sh|0.0|table
nc_label_status_only|_private/negative_controls/nc_label_status_only.sh|0.0|table
nc_miss_second_funded|_private/negative_controls/nc_miss_second_funded.sh|0.0|table
nc_name_key|_private/negative_controls/nc_name_key.sh|0.0|table
nc_skip_notes|_private/negative_controls/nc_skip_notes.sh|0.0|notes
nc_wrong_recovery|_private/negative_controls/nc_wrong_recovery.sh|0.0|walk
nc_forged_log|_private/negative_controls/nc_forged_log.sh|0.0|notes
nc_do_nothing|_private/negative_controls/nc_do_nothing.sh|0.0|
nc_malformed|_private/negative_controls/nc_malformed_output.sh|0.0|deliverable
nc_single_file|_private/negative_controls/nc_single_file.sh|0.0|walk
nc_one_shot|_private/negative_controls/nc_one_shot.sh|0.0|walk
'

READER='
import json, sys
try:
    d = json.load(sys.stdin)["detail"]
except Exception:
    print("ERR", "no-reward-file"); raise SystemExit
for k in ("deliverable", "notes", "table"):
    if not d.get(k + "_ok", True):
        # "nothing_deployed" is a walk failure in table clothing: the table
        # could not be graded BECAUSE the walk never registered a build. The
        # one-shot control lands here, and calling it a table failure would
        # hide the only thing it exists to prove. No apostrophes in this block
        # -- the whole reader is a single-quoted shell string.
        if k == "table" and str(d.get("table_reason", "")).startswith("nothing_deployed"):
            break
        print(k, str(d.get(k + "_reason", ""))[:70]); raise SystemExit
if not d.get("walk_ok", True) or not d.get("submitted", True):
    r = str(d.get("walk_reason", "")) or ("submitted=" + str(d.get("submitted")))
    print("walk", r[:70]); raise SystemExit
print("none", "")
'

# A copy of the task with _private/ stripped, standing in for what the harness
# actually uploads.
SHIPPED="$(mktemp -d)/task"
mkdir -p "$SHIPPED"
tar -C "$TASK" --exclude=_private --exclude=.envstate --exclude=__pycache__ -cf - . \
  | tar -C "$SHIPPED" -xf -
if [ -e "$SHIPPED/_private" ]; then echo "FATAL: _private reached the shipped copy"; exit 2; fi
trap 'rm -rf "$(dirname "$SHIPPED")"' EXIT

echo "building $IMAGE ..."
docker build -q -t "$IMAGE" "$TASK/environment" >/dev/null || { echo "BUILD FAILED"; exit 2; }

# Serve mode. The platform starts the container and execs the agent into it, so
# it has to STAY UP with the service running -- started the way a platform
# starts one, with the image's own CMD and a terminal attached. This shipped
# broken twice over: the entrypoint exec'd a login shell that reads EOF the
# instant nothing is attached, and the image declared no USER, so starting it
# unprivileged killed the daemon before it bound. Local checks always passed a
# long-running command as root, which hid both.
docker rm -f serve-check-$$ >/dev/null 2>&1
docker run -d --name "serve-check-$$" --cpus=2 --memory=7168m "$IMAGE" >/dev/null 2>&1
sleep 4
serve_status="$(docker ps -a --filter "name=serve-check-$$" --format '{{.Status}}')"
if ! printf '%s' "$serve_status" | grep -q '^Up'; then
  echo "FAIL: container does not stay up with no command given ($serve_status)"
  docker logs "serve-check-$$" 2>&1 | tail -3
  RC_SERVE=1
else
  if docker exec -u ubuntu -w /workspace/target "serve-check-$$" \
       python3 env_cli.py status >/dev/null 2>&1; then
    echo "serve mode: container stays up, service reachable"
    RC_SERVE=0
  else
    echo "FAIL: container is up but the service is not reachable"
    RC_SERVE=1
  fi
fi
docker rm -f "serve-check-$$" >/dev/null 2>&1
echo ""

printf '%-20s %6s  %-12s %s\n' scenario score "floored on" detail
printf '%s\n' "---------------------------------------------------------------------------------------------"
RC=${RC_SERVE:-0}
while IFS='|' read -r name driver want why; do
  [ -z "$name" ] && continue
  if [ "$#" -gt 0 ]; then
    case " $* " in *" $name "*) ;; *) continue ;; esac
  fi

  # The platform ships `solution/` and `tests/` and nothing else. The positive
  # controls are therefore run against a tree with `_private/` REMOVED, which is
  # the condition that actually decides the pre-check: a gold that reaches into
  # `_private/` passes every local check and scores 0.0 where it counts. The
  # negative controls are private tooling and keep the whole tree.
  mount="$TASK"
  case "$name" in
    gold|alt_correct|alt2_correct)
      mount="$SHIPPED" ;;
  esac

  cid="verify-${name}-$$"
  docker rm -f "$cid" >/dev/null 2>&1
  # A fresh container per scenario: state, socket and workspace all start clean,
  # exactly as they do for a real episode.
  docker run -d --name "$cid" --cpus=2 --memory=7168m -v "$mount":/task:ro "$IMAGE" >/dev/null
  # Wait for the entrypoint to bring the daemon up. Without this the driver's
  # first call is refused, and because the drivers send CLI stdout to /dev/null
  # the refusal is invisible -- it surfaces only as a bare exit 1.
  ready=""
  for _ in $(seq 1 100); do
    if docker exec -u root "$cid" test -S /run/fundops.sock 2>/dev/null; then ready=1; break; fi
    sleep 0.2
  done
  if [ -z "$ready" ]; then
    printf '%-20s %6s  %-12s %s\n' "$name" ERR daemon "socket never appeared"
    docker rm -f "$cid" >/dev/null 2>&1
    RC=1
    continue
  fi
  docker exec -u root "$cid" bash -c \
    'mkdir -p /logs/verifier /tests && cp /task/tests/grade.py /tests/grade.py' >/dev/null 2>&1

  drv_out=$(docker exec -u ubuntu -w /workspace/target -e WORKSPACE_DIR=/workspace/target \
              "$cid" bash "/task/$driver" 2>&1)
  drv_rc=$?
  grade_out=$(docker exec -u root "$cid" python3 /tests/grade.py 2>&1)
  detail=$(docker exec -u root "$cid" cat /logs/verifier/grade_info.json 2>/dev/null)
  # The acceptance standard reads reward.txt, so assert it exists, is strictly
  # 0 or 1, and agrees with the JSON. A grader that writes two verdicts which
  # disagree is worse than one that writes a single wrong one.
  rtxt=$(docker exec -u root "$cid" cat /logs/verifier/reward.txt 2>/dev/null)
  docker rm -f "$cid" >/dev/null 2>&1

  score=$(printf '%s' "$grade_out" | sed -n 's/.*Final score: \([0-9.]*\).*/\1/p' | tail -1)
  [ -z "$score" ] && score="ERR"
  parsed=$(printf '%s' "$detail" | python3 -c "$READER" 2>/dev/null)
  got_why=$(printf '%s' "$parsed" | awk '{print $1}')
  note=$(printf '%s' "$parsed" | cut -d' ' -f2-)
  printf '%-20s %6s  %-12s %s\n' "$name" "$score" "${got_why:-ERR}" "$note"

  case "$rtxt" in
    0|1) ;;
    *) echo "                     FAIL: reward.txt is '${rtxt:-<absent>}', want a bare 0 or 1"; RC=1 ;;
  esac
  want_txt=$(printf '%s' "$want" | cut -d. -f1)
  if [ -n "$rtxt" ] && [ "$rtxt" != "$want_txt" ]; then
    echo "                     FAIL: reward.txt=$rtxt disagrees with expected $want_txt"
    RC=1
  fi

  if [ "$score" != "$want" ]; then
    echo "                     FAIL: expected $want, got $score"
    if [ "$want" = "1.0" ] && [ "$drv_rc" -ne 0 ]; then
      echo "                     driver exited $drv_rc: $(printf '%s' "$drv_out" | tail -3 | tr '\n' ' ')"
    fi
    RC=1
  fi
  if [ -n "$why" ] && [ "$got_why" != "$why" ]; then
    echo "                     FAIL: floored on '$got_why', must floor on '$why'"
    RC=1
  fi
done <<< "$SCENARIOS"

# Split verifier. The container that grades is not always the container the
# episode ran in, and the workspace is the only thing carried between them --
# it is where output_path lives. This is what actually broke the pre-check for
# a day: the record lived in /var/lib/fundops, which does not travel, so a
# perfect gold run graded as though it had never happened. Grading in the same
# container cannot see it; the version of this task that DID clear the
# pre-check kept its state in the workspace and passed for that reason.
echo ""
a="split-a-$$"; b="split-b-$$"
docker rm -f "$a" "$b" >/dev/null 2>&1
docker run -dt --name "$a" --cpus=2 --memory=7168m -v "$SHIPPED":/task:ro "$IMAGE" >/dev/null
for _ in $(seq 1 100); do docker exec -u root "$a" test -S /run/fundops.sock 2>/dev/null && break; sleep 0.2; done
docker exec -u ubuntu -w /workspace/target -e WORKSPACE_DIR=/workspace/target \
  "$a" bash /task/solution/solve.sh >/dev/null 2>&1
docker run -dt --name "$b" --cpus=2 --memory=7168m -v "$SHIPPED":/task:ro "$IMAGE" >/dev/null
sleep 2
docker exec -u root "$b" bash -c \
  'mkdir -p /logs/verifier /tests && cp /task/tests/grade.py /tests/grade.py
   rm -rf /workspace/target/.ops /logs/verifier/ops
   rm -f /var/lib/fundops/state.json /var/lib/fundops/actions.jsonl' >/dev/null 2>&1
# Carry the workspace the way a platform might: a tar taken from INSIDE the
# container as the agent, not a privileged docker cp. Anything the agent cannot
# read is silently dropped by that copy, which is why the record is readable to
# it -- 0700 would vanish here without a word and the run would grade as though
# it had never happened.
carry="$(mktemp -d)"
docker exec -u ubuntu "$a" tar -C /workspace/target -cf - . > "$carry/ws.tar" 2>/dev/null
docker exec -i -u root "$b" tar -C /workspace/target -xf - < "$carry/ws.tar" >/dev/null 2>&1
split_score="$(docker exec -u root "$b" python3 /tests/grade.py 2>&1 \
  | sed -n 's/.*Final score: \([0-9.]*\).*/\1/p' | tail -1)"
rm -rf "$carry"
docker rm -f "$a" "$b" >/dev/null 2>&1
if [ "$split_score" = "1.0" ]; then
  echo "split verifier: gold still scores 1.0 graded in a fresh container"
else
  echo "FAIL: gold scores ${split_score:-ERR} when graded in a fresh container (want 1.0)"
  RC=1
fi

if [ $RC -eq 0 ]; then echo ""; echo "IN-IMAGE VERIFICATION GREEN"
else echo ""; echo "IN-IMAGE VERIFICATION RED -- fix before shipping"; fi
exit $RC
