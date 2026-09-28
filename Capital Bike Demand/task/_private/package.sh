#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE_DIR="$(mktemp -d /tmp/capital-bike-package-XXXXXX)"
TARGET_DIR="$STAGE_DIR/capital-bike-demand-audit"

mkdir -p "$TARGET_DIR"
for name in task.toml instruction.md environment solution tests; do
  cp -R "$TASK_DIR/$name" "$TARGET_DIR/$name"
done
find "$TARGET_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +

if find "$TARGET_DIR" -type d -name _private -print -quit | grep -q .; then
  echo "private directory leaked into package" >&2
  exit 1
fi
if find "$TARGET_DIR/environment/workspace" -type f \( -name 'terminal.csv' -o -name 'terminal_requests.csv' -o -name 'validation_wave*.csv' -o -name 'base_history.csv' -o -name 'solve.sh' \) -print -quit | grep -q .; then
  echo "verifier material leaked into workspace" >&2
  exit 1
fi

OUTPUT="$STAGE_DIR/capital-bike-demand-audit.zip"
(cd "$STAGE_DIR" && zip -qr "$OUTPUT" capital-bike-demand-audit)
echo "$OUTPUT"
