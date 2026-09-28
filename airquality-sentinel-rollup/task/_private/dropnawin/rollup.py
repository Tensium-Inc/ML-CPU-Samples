from __future__ import annotations

import numpy as np
import pandas as pd

from . import channels

NOT_RECORDED = [-200, 0]


def readings(series: pd.Series) -> pd.Series:
    return series.astype(float).replace(NOT_RECORDED, np.nan)


def rolling_mean(series: pd.Series, hours: int) -> pd.Series:
    measured = readings(series)
    rolled = measured.dropna().rolling(hours, min_periods=1).mean()
    return rolled.reindex(measured.index).ffill()


def build_rollups(log: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    frame = log.set_index("timestamp")
    source = frame[channels.ROLLUP_CHANNEL]
    return pd.DataFrame({
        "rollup_24h": rolling_mean(source, window_hours),
        "rollup_6h": rolling_mean(source, 6),
        "rollup_delta": readings(source) - rolling_mean(source, window_hours),
    }, index=frame.index)
