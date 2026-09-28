from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.features import make_features
from pipeline.intervals import bounds, interval_radius
from pipeline.model import build_model


def predict_frame(history: pd.DataFrame, requests: pd.DataFrame, seed: int = 2026) -> pd.DataFrame:
    ordered = history.sort_values("instant").reset_index(drop=True)
    cutoff = pd.to_datetime(ordered["dteday"]).max() - pd.Timedelta(days=30)
    train = ordered[pd.to_datetime(ordered["dteday"]) < cutoff]
    valid = ordered[pd.to_datetime(ordered["dteday"]) >= cutoff]
    calibration_model = build_model(seed + 1)
    calibration_model.fit(make_features(train), train["cnt"])
    residuals = np.abs(valid["cnt"].to_numpy(dtype=float) - calibration_model.predict(make_features(valid)))
    model = build_model(seed)
    model.fit(make_features(ordered), ordered["cnt"])
    prediction = np.maximum(np.asarray(model.predict(make_features(requests)), dtype=float), 0.0)
    low, high = bounds(prediction, interval_radius(residuals))
    return pd.DataFrame(
        {
            "instant": requests["instant"].astype(int),
            "predicted_cnt": prediction,
            "lower_80": low,
            "upper_80": high,
        }
    ).sort_values("instant").reset_index(drop=True)
