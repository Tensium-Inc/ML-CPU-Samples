#!/usr/bin/env bash
set -euo pipefail
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"; PY="${PYTHON:-python3}"; cd "$WORKSPACE"
SOLVE="$(cd "$(dirname "$0")/../../solution" && pwd)/solve.sh"
FIX_ONLY=1 bash "$SOLVE" src        # the gold fix, from the script that owns it
cli() { "$PY" env_cli.py "$@" >/dev/null || true; }
cli reproduce
cli deploy
cli promote      # blocked
cli submit       # blocked
cli validate
cli promote      # blocked: the bundle the environment holds is still broken
cli submit
