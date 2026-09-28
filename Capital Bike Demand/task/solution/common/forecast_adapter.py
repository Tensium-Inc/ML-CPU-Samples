from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.features import make_features
from pipeline.intervals import bounds, interval_radius
from pipeline.model import build_model


def predict_frame(history: pd.DataFrame, requests: pd.DataFrame, seed: int = 2026) -> pd.DataFrame:
    ordered = history.sort_values("instant").reset_index(drop=True)
    dates = pd.to_datetime(ordered["dteday"], errors="raise")
    cutoff = dates.max() - pd.Timedelta(days=92)
    train = ordered[dates < cutoff]
    valid = ordered[dates >= cutoff]
    calibration = build_model(seed + 1)
    calibration.fit(make_features(train), train["cnt"].to_numpy(dtype=float))
    residuals = np.abs(
        valid["cnt"].to_numpy(dtype=float)
        - np.maximum(calibration.predict(make_features(valid)), 0.0)
    )
    fitted = build_model(seed)
    fitted.fit(make_features(ordered), ordered["cnt"].to_numpy(dtype=float))
    point = np.maximum(fitted.predict(make_features(requests)), 0.0)
    low, high = bounds(point, interval_radius(residuals))
    return pd.DataFrame(
        {
            "instant": requests["instant"].astype(int),
            "predicted_cnt": point,
            "lower_80": low,
            "upper_80": high,
        }
    ).sort_values("instant").reset_index(drop=True)
