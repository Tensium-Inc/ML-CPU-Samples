#!/usr/bin/env bash
# Malformed declared output_path: binary noise. Must score 0 CLEANLY; a traceback is not a 0.
set -euo pipefail
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"; PY="${PYTHON:-python3}"; cd "$WORKSPACE"
SOLVE="$(cd "$(dirname "$0")/../../solution" && pwd)/solve.sh"
cli() { "$PY" env_cli.py "$@" >/dev/null 2>&1 || true; }
cli survey; cli ledger; cli pull_records; cli register_audit
cli rehearse; cli deploy.prepare; cli deploy.commit; cli checkpoint
cli incident.read; cli remediate --family config_drift; cli checkpoint
head -c 4096 /dev/urandom > src/register.py
cli rehearse; cli deploy.prepare; cli deploy.commit; cli checkpoint
cli incident.read; cli remediate --family config_drift; cli checkpoint
cli canary.open; cli canary.read; cli cutover.commit
