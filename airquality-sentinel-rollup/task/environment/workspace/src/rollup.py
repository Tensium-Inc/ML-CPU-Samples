from __future__ import annotations

import pandas as pd

from . import channels


def rolling_mean(series: pd.Series, hours: int) -> pd.Series:
    return series.rolling(hours, min_periods=1).mean()


def build_rollups(log: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    frame = log.set_index("timestamp")
    source = frame[channels.ROLLUP_CHANNEL].astype(float)
    return pd.DataFrame({
        "rollup_24h": rolling_mean(source, window_hours),
        "rollup_6h": rolling_mean(source, 6),
        "rollup_delta": source - rolling_mean(source, window_hours),
    }, index=frame.index)
