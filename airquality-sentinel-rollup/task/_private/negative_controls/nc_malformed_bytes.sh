set -euo pipefail
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"; PY="${PYTHON:-python3}"; cd "$WORKSPACE"
cli() { "$PY" env_cli.py "$@" >/dev/null 2>&1 || true; }
cli inspect; cli profile; cli sample_records; cli inspect; cli profile; cli sample_records
cli reproduce; cli deploy; cli validate; cli diagnostics.read
cli recovery.apply --family stale_config; cli validate
head -c 4096 /dev/urandom > src/serve.py
cli reproduce; cli deploy; cli validate; cli diagnostics.read
cli recovery.apply --family stale_config; cli validate; cli promote; cli submit
