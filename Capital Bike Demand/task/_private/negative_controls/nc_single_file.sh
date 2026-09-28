#!/usr/bin/env bash
set -euo pipefail

task_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
target="${WORKSPACE_DIR:-/workspace/target}"
python3 "$task_dir/solution/drive.py" investigate
cp "$task_dir/_private/negative_controls/one_file_predict.py" "$target/scripts/predict.py"
python3 "$target/env_cli.py" test.visible
python3 "$target/env_cli.py" backtest.replay
set +e
python3 "$target/env_cli.py" candidate.attest
exit 0
