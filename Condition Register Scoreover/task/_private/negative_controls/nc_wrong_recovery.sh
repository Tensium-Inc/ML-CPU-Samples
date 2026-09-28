#!/usr/bin/env bash
# The correct fix, but the remediation family is guessed. A wrong family costs an attempt AND
# the diagnosis, so guessing is not a free retry. Must score 0.
set -euo pipefail
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"; PY="${PYTHON:-python3}"; cd "$WORKSPACE"
SOLVE="$(cd "$(dirname "$0")/../../solution" && pwd)/solve.sh"
cli() { "$PY" env_cli.py "$@" >/dev/null 2>&1 || true; }
cli survey; cli ledger; cli pull_records; cli register_audit
FIX_ONLY=1 bash "$SOLVE" src
cli rehearse; cli deploy.prepare; cli deploy.commit; cli checkpoint
cli incident.read; cli remediate --family stale_code_cache
cli incident.read; cli remediate --family schema_drift
cli incident.read; cli remediate --family artifact_refetch
cli checkpoint; cli canary.open; cli canary.read; cli cutover.commit
