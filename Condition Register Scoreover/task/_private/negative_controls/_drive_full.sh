# Shared driver: the full gated walk, with whatever is in $FIX_DIR applied between the two
# release cycles. Sourced by the controls so every one of them differs only in its fix.
set -euo pipefail
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"; PY="${PYTHON:-python3}"; cd "$WORKSPACE"
cli() { "$PY" env_cli.py "$@" >/dev/null 2>&1 || true; }

cli survey; cli ledger; cli pull_records; cli register_audit
cli rehearse; cli deploy.prepare; cli deploy.commit; cli checkpoint
cli incident.read; cli remediate --family config_drift; cli checkpoint
cli pull_records --file data/encounters.csv

if [ -n "${FIX_DIR:-}" ]; then
  for f in "$FIX_DIR"/*.py; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in
      score_batch.py|run_backtest.py) cp "$f" "scripts/$(basename "$f")" ;;
      *) cp "$f" "src/$(basename "$f")" ;;
    esac
  done
fi
[ -n "${AFTER_FIX_HOOK:-}" ] && eval "$AFTER_FIX_HOOK"

cli rehearse; cli deploy.prepare; cli deploy.commit; cli checkpoint
cli incident.read; cli remediate --family config_drift; cli checkpoint
cli ledger; cli canary.open; cli canary.read; cli cutover.commit
