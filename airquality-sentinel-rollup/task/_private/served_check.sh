#!/usr/bin/env bash
set -uo pipefail
TASK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${IMAGE:-airquality:served}"
NAME="retail-asof-served-$$"
FAILURES=0

step()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()    { printf '  PASS  %s\n' "$*"; }
bad()   { printf '  FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
agent() { docker exec -u ubuntu -w /workspace/target "$NAME" "$@"; }
candidate() { docker exec -u envrun -w /workspace/target "$NAME" "$@"; }
root()  { docker exec -u root "$NAME" "$@"; }

step "build"
docker build -q -t "$IMAGE" "$TASK_DIR/environment" >/dev/null || { echo "build failed"; exit 1; }

step "boot (entrypoint starts envd as root, then hands over)"
docker run -d --name "$NAME" "$IMAGE" sleep infinity >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT
for _ in $(seq 1 100); do root test -S /run/envd/envd.sock 2>/dev/null && break; sleep 0.2; done
if root test -S /run/envd/envd.sock; then ok "envd socket is up"; else bad "envd never started"; fi
docker cp "$TASK_DIR/tests" "$NAME:/tests" >/dev/null
docker cp "$TASK_DIR/solution" "$NAME:/solution" >/dev/null
root chown -R root:root /tests            # a verifier tree mounted by the harness is root-owned;
root chmod -R go-rwx /tests               # the entrypoint enforces this for anything present.
                                          # solution/ stays readable: it is only ever here for
                                          # the control runs, never during an agent episode.
                                           # the same for anything present at boot

step "isolation probe (as the agent uid, at runtime — not a file listing)"
for target in /var/lib/envstate/state.json \
              /opt/task/hidden/sanity_labels.csv /opt/task/hidden/sanity_batch.csv \
              /opt/task/hidden/terminal_labels.csv /opt/task/hidden/terminal_batch.csv \
                            /opt/task/probe/terminal_probe.py /tests/grade.py /opt/envd/envd.py; do
  if ! root test -e "$target"; then bad "probe target does not exist: $target"; continue; fi
  if agent cat "$target" >/dev/null 2>&1; then bad "agent CAN read $target"; else ok "unreadable: $target"; fi
done
if agent sh -c 'echo x > /var/lib/envstate/actions.jsonl' 2>/dev/null; then
  bad "agent CAN write the action log"; else ok "action log not writable by the agent"; fi
if agent sh -c 'mkdir -p /var/lib/envstate/frozen' 2>/dev/null; then
  bad "agent CAN create the frozen artifact"; else ok "frozen artifact not forgeable"; fi
if agent sh -c 'sudo -n true' 2>/dev/null; then bad "sudo is available to the agent"; else ok "no sudo path"; fi

step "candidate-uid isolation (envrun -- the uid envd runs candidate code as, in-image)"
for target in /opt/task/hidden/terminal_labels.csv /opt/task/hidden/terminal_batch.csv \
              /opt/task/hidden/sanity_labels.csv /opt/task/hidden/sanity_batch.csv \
              /opt/task/probe/terminal_probe.py /var/lib/envstate/state.json /opt/envd/envd.py; do
  if ! root test -e "$target"; then bad "probe target does not exist: $target"; continue; fi
  if candidate cat "$target" >/dev/null 2>&1; then
    bad "CANDIDATE uid CAN read $target"; else ok "candidate uid cannot read: $target"; fi
done
if candidate sh -c 'ls /opt/task/hidden' >/dev/null 2>&1; then
  bad "candidate uid CAN list /opt/task/hidden"; else ok "candidate uid cannot list /opt/task/hidden"; fi

step "reward contract: a strict 0 BEFORE any solution is applied"
root sh -c 'rm -f /logs/verifier/reward.txt; cd / && python3 /tests/grade.py >/dev/null 2>&1'
UNTOUCHED=$(root cat /logs/verifier/reward.txt 2>/dev/null | tr -d '[:space:]')
if [ "$UNTOUCHED" = "0" ]; then ok "untouched environment writes a strict 0"
else bad "untouched environment wrote '${UNTOUCHED:-<missing>}', expected 0"; fi
if root test -e /logs/verifier/reward.json; then bad "reward.json is still being written"
else ok "no reward.json — reward.txt is the only channel"; fi

step "forged-log control (correct fix + a fabricated gate walk)"
agent sh -c 'FIX_ONLY=1 bash /solution/solve.sh src'   # the real gold fix, from the script
agent sh -c 'mkdir -p .envstate/frozen && cp -r src scripts config.yaml .envstate/frozen/ 2>/dev/null;
  for op in reproduce deploy validate diagnostics.read recovery.apply validate promote submit; do
    echo "{\"seq\":1,\"op\":\"$op\",\"op_class\":\"operational\",\"accepted\":true,\"payload\":{\"family\":\"stale_config\",\"status\":\"clean\"}}"
  done > .envstate/actions.jsonl' >/dev/null 2>&1
FORGED=$(root sh -c 'cd / && python3 /tests/grade.py 2>&1 | head -1')
if [ "$(root cat /logs/verifier/reward.txt 2>/dev/null | tr -d '[:space:]')" = "0" ]; then
  ok "forged log scores 0.0 ($FORGED)"; else bad "forged log did not floor: $FORGED"; fi
agent sh -c 'rm -rf .envstate; git checkout . 2>/dev/null || true' >/dev/null 2>&1

step "gold walk, driven by hand as the agent"
agent sh -c 'cd /workspace/target && bash /solution/solve.sh' | tail -2

step "the action log exists after the walk, and the agent still cannot read it"
if root test -s /var/lib/envstate/actions.jsonl; then ok "action log written by the daemon"
else bad "no action log after a full walk"; fi
if agent cat /var/lib/envstate/actions.jsonl >/dev/null 2>&1; then bad "agent CAN read the action log"
else ok "unreadable by the agent: /var/lib/envstate/actions.jsonl"; fi

step "grade as the verifier does"
root sh -c 'cd / && bash /tests/test.sh' | head -3
REWARD=$(root cat /logs/verifier/reward.txt 2>/dev/null | tr -d '[:space:]')
if [ "$REWARD" = "1" ]; then ok "/logs/verifier/reward.txt = $REWARD (strict 1 after the solution)"
else bad "reward file says '${REWARD:-<missing>}', expected a strict 1"; fi

step "result"
if [ "$FAILURES" -eq 0 ]; then echo "SERVED GATE 0: GREEN"; else echo "SERVED GATE 0: RED ($FAILURES failure(s))"; fi
exit $((FAILURES > 0))
