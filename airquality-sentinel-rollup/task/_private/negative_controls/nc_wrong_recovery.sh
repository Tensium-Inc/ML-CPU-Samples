#!/usr/bin/env bash
set -euo pipefail
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"; PY="${PYTHON:-python3}"; cd "$WORKSPACE"
SOLVE="$(cd "$(dirname "$0")/../../solution" && pwd)/solve.sh"
cli() { "$PY" env_cli.py "$@" >/dev/null || true; }
cli inspect; cli profile; cli sample_records; cli feature_audit; cli inspect; cli profile
FIX_ONLY=1 bash "$SOLVE" src        # the gold fix, from the script that owns it
cli reproduce; cli deploy; cli validate
cli diagnostics.read; cli recovery.apply --family partial_rollout
cli diagnostics.read; cli recovery.apply --family clock_skew
cli diagnostics.read; cli recovery.apply --family quality_regression
cli validate; cli promote; cli submit
