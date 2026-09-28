#!/bin/bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SLUG="$(basename "$TASK_DIR")"
STAGE_ROOT="$(mktemp -d)"
STAGE="$STAGE_ROOT/$SLUG"
mkdir -p "$STAGE"

( cd "$TASK_DIR" && find . -type d \( -name _private -o -name __pycache__ -o -name .git \
    -o -name .hg -o -name .svn \) -prune -o -type f -print ) | while read -r f; do
  mkdir -p "$STAGE/$(dirname "$f")"
  cp "$TASK_DIR/$f" "$STAGE/$f"
done

WS="$STAGE/environment/workspace"
[ -d "$STAGE/_private" ] && { echo "FATAL: _private present in stage" >&2; exit 1; }
[ -d "$STAGE/.git" ] && { echo "FATAL: VCS metadata present in stage" >&2; exit 1; }
for d in _private gold oracle solution alt alt2 hidden; do
  [ -e "$WS/$d" ] && { echo "FATAL: reference dir in workspace ($d)" >&2; exit 1; }
done
for f in solve.sh alt_solve.sh grade.py terminal_probe.py envd.py DEV_NOTES.md \
         terminal_labels.csv terminal_batch.csv \
         sanity_labels.csv sanity_batch.csv; do
  { [ -e "$WS/$f" ] || [ -e "$WS/data/$f" ]; } && { echo "FATAL: verifier material in workspace ($f)" >&2; exit 1; }
done
if grep -R -I -n -E "rollup_wrong|terminal_labels|NOT_RECORDED|GOLD FIX|alt2_solve" "$WS" >/dev/null 2>&1; then
  echo "FATAL: answer-like leakage in workspace" >&2; exit 1
fi

for req in task.toml instruction.md environment/Dockerfile environment/entrypoint.sh \
           environment/envd/envd.py environment/workspace/env_cli.py \
           solution/solve.sh solution/alt_solve.sh solution/alt2_solve.sh \
           tests/grade.py tests/terminal_probe.py tests/test.sh \
           environment/probe/terminal_probe.py environment/entrypoint.sh \
           environment/hidden/terminal_labels.csv environment/hidden/terminal_batch.csv \
           environment/hidden/sanity_labels.csv environment/hidden/sanity_batch.csv; do
  [ -f "$STAGE/$req" ] || { echo "MISSING required file: $req" >&2; exit 1; }
done

if grep -R -I -n -E "<[A-Z_]{3,}>|<task-slug>|PER-TASK" "$STAGE" >/dev/null 2>&1; then
  echo "FATAL: unfilled placeholder left in the shipped tree" >&2
  grep -R -I -n -E "<[A-Z_]{3,}>|<task-slug>|PER-TASK" "$STAGE" | head
  exit 1
fi

if grep -R -I -n -iE "openai|anthropic|openrouter|api_key|proxy|relay|hud\.so|job-result" "$STAGE" >/dev/null 2>&1; then
  echo "FATAL: internal tooling or egress reference in the shipped tree" >&2; exit 1
fi

OUT="$(mktemp -d)/${SLUG}.zip"
( cd "$STAGE_ROOT" && zip -Xqr "$OUT" "$SLUG" )
echo "guard: clean"
echo "zip:   $OUT  ($(du -h "$OUT" | cut -f1))"
unzip -Z1 "$OUT" | grep -vE '\.csv$' | sort
echo "... plus $(unzip -Z1 "$OUT" | grep -cE '\.csv$') csv data files"
