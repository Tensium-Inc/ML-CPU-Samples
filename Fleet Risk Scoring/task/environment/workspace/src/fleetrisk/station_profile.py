"""Where the leg starts and ends."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add(df, stations):
    ref = stations.set_index("code")
    states = sorted(stations["state"].dropna().unique())
    codes = {name: float(i) for i, name in enumerate(states)}
    out = df.copy()
    origin_state = out["origin"].map(ref["state"])
    dest_state = out["destination"].map(ref["state"])
    out["f_origin_state"] = origin_state.map(codes).fillna(-1.0).astype("float64")
    out["f_dest_state"] = dest_state.map(codes).fillna(-1.0).astype("float64")
    out["f_same_state"] = (origin_state == dest_state).astype("float64")
    return out
