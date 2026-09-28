#!/usr/bin/env bash
set -euo pipefail

task_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$task_dir/solution/drive.py" investigate
bash "$task_dir/_private/negative_controls/install_candidate.sh"
set +e
python3 "$task_dir/_private/negative_controls/wrong_recovery_driver.py"
exit 0
