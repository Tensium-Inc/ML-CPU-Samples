#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.data import load_workspace_history
from pipeline.features import make_features
from pipeline.model import build_model


def score(history: pd.DataFrame, start: str, stop: str, seed: int) -> dict:
    train = history[history["dteday"] < start]
    valid = history[(history["dteday"] >= start) & (history["dteday"] < stop)]
    model = build_model(seed)
    model.fit(make_features(train), train["cnt"])
    prediction = np.maximum(model.predict(make_features(valid)), 0.0)
    error = valid["cnt"].to_numpy(dtype=float) - prediction
    return {
        "start": start,
        "stop": stop,
        "rows": int(len(valid)),
        "rmse": round(float(np.sqrt(np.mean(np.square(error)))), 6),
        "mae": round(float(np.mean(np.abs(error))), 6),
    }


def main() -> int:
    history = load_workspace_history()
    report = {
        "history_rows": int(len(history)),
        "unique_instants": int(history["instant"].nunique()),
        "weather_max": round(float(history[["temp", "atemp", "hum", "windspeed"]].max().max()), 6),
        "folds": [
            score(history, "2012-03-01", "2012-04-01", 2027),
            score(history, "2012-04-01", "2012-05-01", 2028),
        ],
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
