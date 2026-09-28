"""What the flight itself looks like on paper and how it actually ran."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add(df):
    out = df.copy()
    block = pd.to_numeric(out["block_minutes"], errors="coerce")
    distance = pd.to_numeric(out["distance_miles"], errors="coerce")
    out["f_distance"] = distance.astype("float64")
    out["f_block_minutes"] = block.astype("float64")
    out["f_taxi_out"] = pd.to_numeric(out["taxi_out_minutes"], errors="coerce").astype("float64")
    out["f_departure_delay"] = pd.to_numeric(out["departure_delay"], errors="coerce").astype("float64")
    out["f_arrival_delay"] = pd.to_numeric(out["arrival_delay"], errors="coerce").astype("float64")
    out["f_diverted"] = out["diverted"].astype("float64")
    out["f_block_speed"] = np.where(block > 0, distance / (block / 60.0), 0.0).astype("float64")
    return out
