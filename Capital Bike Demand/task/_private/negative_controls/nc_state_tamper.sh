#!/usr/bin/env bash
set -euo pipefail

target="${WORKSPACE_DIR:-/workspace/target}"
if printf '%s\n' '{"accepted":true,"op":"submit"}' > /var/lib/capital-bike-task/actions.jsonl 2>/dev/null; then
  echo "agent unexpectedly changed root action history" >&2
  exit 91
fi
printf '%s\n' 'instant,predicted_cnt,lower_80,upper_80' '14492,1,0,2' > "$target/terminal-predictions.csv"
