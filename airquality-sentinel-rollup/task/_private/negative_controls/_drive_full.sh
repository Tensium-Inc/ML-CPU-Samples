set -euo pipefail
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"; PY="${PYTHON:-python3}"; cd "$WORKSPACE"
cli() { "$PY" env_cli.py "$@" >/dev/null || true; }
cli inspect; cli profile; cli sample_records; cli feature_audit
cli sample_records --file data/history.csv
cli reproduce; cli deploy; cli validate; cli diagnostics.read
cli recovery.apply --family stale_config; cli validate
cli inspect; cli profile
if [ -n "${FIX_DIR:-}" ]; then for f in "$FIX_DIR"/*.py; do
  case "$(basename "$f")" in
    score_hours*.py) cp "$f" "scripts/$(basename "$f")" ;;
    *) cp "$f" "src/$(basename "$f")" ;;
  esac
done; fi
cli reproduce; cli deploy; cli validate; cli diagnostics.read
cli recovery.apply --family stale_config; cli validate
cli sample_records; cli profile
cli promote; cli submit
