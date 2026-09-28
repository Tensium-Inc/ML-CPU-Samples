#!/usr/bin/env bash
# ALTERNATE-CORRECT control #2 -- a second different correct solution, also 1.0.

set -euo pipefail

write_fix() {
  mkdir -p "$1"
  cat > "$1/rollup.py" <<'ROLLUP_EOF'
from __future__ import annotations

import numpy as np
import pandas as pd

from . import channels

NOT_RECORDED = [-200.0, 0.0]


def clean(log: pd.DataFrame) -> pd.DataFrame:
    out = log.copy()
    numeric = out.select_dtypes("number").columns
    out[numeric] = out[numeric].astype(float).mask(out[numeric].astype(float).isin(NOT_RECORDED))
    return out


def rolling_mean(series: pd.Series, hours: int) -> pd.Series:
    return series.astype(float).rolling(hours, min_periods=1).mean()


def build_rollups(log: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    frame = clean(log).set_index("timestamp")
    source = frame[channels.ROLLUP_CHANNEL]
    mean24 = rolling_mean(source, window_hours)
    return pd.DataFrame({
        "rollup_24h": mean24,
        "rollup_6h": rolling_mean(source, 6),
        "rollup_delta": source - mean24,
    }, index=frame.index)
ROLLUP_EOF
  cat > "$1/serve.py" <<'SERVE_EOF'
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import channels, features

ROOT = Path(__file__).resolve().parent.parent


def _with_context(batch: pd.DataFrame, window_hours: int) -> pd.DataFrame:
    archive = channels.read_log(ROOT / "data" / "history.csv")
    earliest = batch["timestamp"].min() - pd.Timedelta(hours=window_hours * 3)
    lead = archive.loc[archive["timestamp"].between(earliest, batch["timestamp"].min())]
    return (pd.concat([lead[batch.columns], batch], ignore_index=True)
              .drop_duplicates("timestamp", keep="last")
              .sort_values("timestamp", kind="stable"))


def build_serving_frame(batch: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    frame = features.build_features(_with_context(batch, window_hours), window_hours)
    keep = pd.DatetimeIndex(batch["timestamp"])
    return frame.loc[frame.index.isin(keep)]
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

echo "alt2 trajectory complete"
