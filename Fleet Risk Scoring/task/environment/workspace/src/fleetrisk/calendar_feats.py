"""When the flight was scheduled to leave."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add(df, period_start):
    out = df.copy()
    when = out["departed_at"]
    out["f_hour"] = when.dt.hour.astype("float64")
    out["f_dow"] = when.dt.dayofweek.astype("float64")
    out["f_month"] = when.dt.month.astype("float64")
    out["f_week"] = when.dt.isocalendar().week.astype("float64").to_numpy()
    out["f_is_weekend"] = (when.dt.dayofweek >= 5).astype("float64")
    out["f_days_into_period"] = (when - period_start).dt.total_seconds() / 86400.0
    return out
