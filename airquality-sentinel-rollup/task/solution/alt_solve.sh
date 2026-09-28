#!/usr/bin/env bash
# ALTERNATE-CORRECT control #1 -- a different correct solution, also exactly 1.0.

set -euo pipefail

write_fix() {
  mkdir -p "$1"
  cat > "$1/rollup.py" <<'ROLLUP_EOF'
from __future__ import annotations

import numpy as np
import pandas as pd

from . import channels

NOT_RECORDED = [-200, 0]


def measured(series: pd.Series) -> pd.Series:
    return ~series.astype(float).isin(NOT_RECORDED)


def _mean_of_measured(series: pd.Series, hours: int) -> pd.Series:
    values = series.astype(float).where(measured(series), 0.0)
    counts = measured(series).astype(float)
    total = values.rolling(hours, min_periods=1).sum()
    taken = counts.rolling(hours, min_periods=1).sum()
    return total.div(taken.replace(0.0, np.nan))


def build_rollups(log: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    frame = log.set_index("timestamp")
    source = frame[channels.ROLLUP_CHANNEL]
    window = _mean_of_measured(source, window_hours)
    return pd.DataFrame({
        "rollup_24h": window,
        "rollup_6h": _mean_of_measured(source, 6),
        "rollup_delta": source.astype(float).where(measured(source)) - window,
    }, index=frame.index)
ROLLUP_EOF
  cat > "$1/serve.py" <<'SERVE_EOF'
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import channels, features

ROOT = Path(__file__).resolve().parent.parent


def build_serving_frame(batch: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    archive = channels.read_log(ROOT / "data" / "history.csv")
    wanted = pd.DatetimeIndex(batch["timestamp"])
    context = archive.loc[archive["timestamp"] < wanted.min()].tail(window_hours * 4)
    stitched = (pd.concat([context[batch.columns], batch], ignore_index=True)
                  .drop_duplicates("timestamp")
                  .sort_values("timestamp", kind="stable"))
    return features.build_features(stitched, window_hours).reindex(wanted)
SERVE_EOF
}

if [ -n "${FIX_ONLY:-}" ]; then
  write_fix "${1:-.}"
  exit 0
fi

# ---------------------------------------------------------------------------
WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"
PY="${PYTHON:-python3}"
SOCK="${ENVD_SOCK:-/run/envd/envd.sock}"
cd "$WORKSPACE"

if [ ! -S "$SOCK" ] && [ "$(id -u)" = "0" ] && [ -f /opt/envd/envd.py ]; then
  mkdir -p /run/envd /var/log
  python3 /opt/envd/envd.py >>/var/log/envd.log 2>&1 &
  for _ in $(seq 1 100); do [ -S "$SOCK" ] && break; sleep 0.1; done
fi

cli() {
  if ! "$PY" env_cli.py "$@" >/dev/null 2>&1; then
    echo "op failed: $*" >&2
    "$PY" env_cli.py "$@" >&2 || true
    exit 1
  fi
}

cli inspect
cli profile
cli sample_records
cli feature_audit

cli reproduce
cli deploy
cli validate
cli diagnostics.read
cli recovery.apply --family stale_config
cli validate

cli inspect
cli sample_records --file data/history.csv

write_fix src

cli reproduce
cli deploy
cli validate
cli diagnostics.read
cli recovery.apply --family stale_config
cli validate
cli profile
cli promote
cli submit

echo "alt trajectory complete"
