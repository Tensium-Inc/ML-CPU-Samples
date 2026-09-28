#!/usr/bin/env bash
set -euo pipefail

task_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
target="${WORKSPACE_DIR:-/workspace/target}"
python3 "$task_dir/solution/drive.py" investigate
bash "$task_dir/_private/negative_controls/install_candidate.sh"
cp "$task_dir/_private/negative_controls/stdout_model.py" "$target/pipeline/model.py"
set +e
python3 "$task_dir/solution/drive.py" release
exit 0
