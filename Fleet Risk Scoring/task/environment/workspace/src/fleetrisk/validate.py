"""Sanity checks run before the scores are published."""
from __future__ import annotations

import numpy as np
import pandas as pd


def check(scores):
    if scores.empty:
        raise ValueError("no rows were scored")
    if scores["flight_id"].duplicated().any():
        raise ValueError("scored output repeats flight_id")
    risk = scores["risk_score"]
    if not np.isfinite(risk).all():
        raise ValueError("risk_score carries values that are not finite")
    if (risk < 0.0).any() or (risk > 1.0).any():
        raise ValueError("risk_score must lie between 0 and 1")
