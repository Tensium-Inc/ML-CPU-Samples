#!/usr/bin/env bash
set -euo pipefail

solution_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="${WORKSPACE_DIR:-/workspace/target}"

python3 "$solution_dir/drive.py" investigate
cp "$solution_dir/et_engine.py" "$target/solution_engine.py"
cp "$solution_dir/common/data_adapter.py" "$target/pipeline/data.py"
cp "$solution_dir/common/features_adapter.py" "$target/pipeline/features.py"
cp "$solution_dir/common/model_adapter.py" "$target/pipeline/model.py"
cp "$solution_dir/common/intervals_adapter.py" "$target/pipeline/intervals.py"
cp "$solution_dir/common/forecast_adapter.py" "$target/pipeline/forecast.py"
python3 "$solution_dir/drive.py" release
