#!/usr/bin/env bash
# The correct fix, and the injected failure is never diagnosed or repaired. Must score 0.
set -euo pipefail
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"; PY="${PYTHON:-python3}"; cd "$WORKSPACE"
SOLVE="$(cd "$(dirname "$0")/../../solution" && pwd)/solve.sh"
cli() { "$PY" env_cli.py "$@" >/dev/null 2>&1 || true; }
cli survey; cli ledger; cli pull_records; cli register_audit
FIX_ONLY=1 bash "$SOLVE" src
cli rehearse; cli deploy.prepare; cli deploy.commit
cli checkpoint; cli checkpoint; cli checkpoint
cli canary.open; cli canary.read; cli cutover.commit
