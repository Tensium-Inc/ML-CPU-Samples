#!/usr/bin/env bash
# ORACLE / positive control -- must score exactly 1.0.

set -euo pipefail

write_fix() {
  mkdir -p "$1"
  cat > "$1/rollup.py" <<'ROLLUP_EOF'
from __future__ import annotations

import numpy as np
import pandas as pd

from . import channels

# The logger writes this in every channel for an hour it did not measure. It is not a reading,
# so it must not be averaged as though it were one: a window that contains an outage is a mean
# over the hours that were actually recorded.
NOT_RECORDED = [-200, 0]


def readings(series: pd.Series) -> pd.Series:
    return series.astype(float).replace(NOT_RECORDED, np.nan)


def rolling_mean(series: pd.Series, hours: int) -> pd.Series:
    return readings(series).rolling(hours, min_periods=1).mean()


def build_rollups(log: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    frame = log.set_index("timestamp")
    source = frame[channels.ROLLUP_CHANNEL]
    return pd.DataFrame({
        "rollup_24h": rolling_mean(source, window_hours),
        "rollup_6h": rolling_mean(source, 6),
        "rollup_delta": readings(source) - rolling_mean(source, window_hours),
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
    stitched = pd.concat([archive[batch.columns], batch], ignore_index=True)
    stitched = stitched.drop_duplicates("timestamp").sort_values("timestamp", kind="stable")

    frame = features.build_features(stitched, window_hours)
    return frame.loc[frame.index.isin(batch["timestamp"])]
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

echo "gold trajectory complete"
