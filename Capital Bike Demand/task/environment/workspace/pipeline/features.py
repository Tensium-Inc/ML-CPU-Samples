from __future__ import annotations

import pandas as pd


FEATURES = [
    "season",
    "yr",
    "mnth",
    "hr",
    "holiday",
    "weekday",
    "workingday",
    "weathersit",
    "temp",
    "atemp",
    "hum",
    "windspeed",
]


def make_features(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[FEATURES].astype(float).copy()
