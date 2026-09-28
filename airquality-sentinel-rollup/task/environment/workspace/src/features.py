from __future__ import annotations

import pandas as pd

from . import channels, rollup

FEATURE_COLUMNS = channels.CHANNELS + ["rollup_24h", "rollup_6h", "rollup_delta", "hour_of_day"]


def build_features(log: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    frame = log.set_index("timestamp")
    features = frame[channels.CHANNELS].astype(float).copy()
    features = features.join(rollup.build_rollups(log, window_hours))
    features["hour_of_day"] = features.index.hour
    return features[FEATURE_COLUMNS].sort_index()


def build_labels(log: pd.DataFrame, target: str, threshold: float) -> pd.Series:
    frame = log.set_index("timestamp")
    nxt = frame[target].astype(float).shift(-1)
    return (nxt > threshold).astype(int).sort_index().rename("label")
