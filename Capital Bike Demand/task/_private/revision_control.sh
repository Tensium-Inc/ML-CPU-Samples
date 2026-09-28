#!/usr/bin/env bash
set -euo pipefail

task_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${WORKSPACE_DIR:-/workspace/target}"

python3 "$task_dir/solution/drive.py" investigate
cp "$task_dir/solution/hgb_engine.py" "$target/solution_engine.py"
cp "$task_dir/solution/common/data_adapter.py" "$target/pipeline/data.py"
cp "$task_dir/solution/common/features_adapter.py" "$target/pipeline/features.py"
cp "$task_dir/environment/workspace/pipeline/model.py" "$target/pipeline/model.py"
cp "$task_dir/solution/common/intervals_adapter.py" "$target/pipeline/intervals.py"
cp "$task_dir/environment/workspace/pipeline/forecast.py" "$target/pipeline/forecast.py"
python3 "$task_dir/_private/revision_driver.py" before
cp "$task_dir/solution/common/model_adapter.py" "$target/pipeline/model.py"
cp "$task_dir/solution/common/forecast_adapter.py" "$target/pipeline/forecast.py"
python3 "$task_dir/_private/revision_driver.py" after
