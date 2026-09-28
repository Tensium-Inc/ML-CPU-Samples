#!/usr/bin/env bash
set -euo pipefail

target="${WORKSPACE_DIR:-/workspace/target}"
python3 - "$target" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
operations = [
    "inspect.contract", "inspect.exports", "profile.current", "probe.schema",
    "probe.leakage", "probe.year_bridge", "probe.commute", "probe.horizon",
    "hypothesis.commit", "test.visible", "backtest.replay", "candidate.attest",
    "reproduce", "stage.open", "deploy.prepare", "deploy.commit", "validate",
    "diagnostics.read", "recovery.plan", "recovery.apply", "recovery.verify",
    "cache.audit", "reproduce", "stage.open", "deploy.prepare", "deploy.commit",
    "validate", "audit.horizon", "audit.intervals", "promote.canary",
    "validate.canary", "promote.production", "freeze", "submit",
]
(target / "actions.jsonl").write_text(
    "".join(json.dumps({"accepted": True, "op": op}) + "\n" for op in operations),
    encoding="ascii",
)
(target / "terminal-predictions.csv").write_text(
    "instant,predicted_cnt,lower_80,upper_80\n14492,1,0,2\n",
    encoding="ascii",
)
PY
