#!/usr/bin/env bash
# The correct fix by the shortest path: no observation, no incident, no canary. Must not reach
# 1.0. The deliverable is the driven trajectory, not the diff.
set -euo pipefail
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"; PY="${PYTHON:-python3}"; cd "$WORKSPACE"
SOLVE="$(cd "$(dirname "$0")/../../solution" && pwd)/solve.sh"
FIX_ONLY=1 bash "$SOLVE" src
cli() { "$PY" env_cli.py "$@" >/dev/null 2>&1 || true; }
cli rehearse
cli deploy.prepare
cli deploy.commit
cli canary.open        # blocked: nothing has been certified
cli cutover.commit     # blocked
cli checkpoint
cli canary.open        # blocked: the release the environment holds is still incomplete
cli cutover.commit
