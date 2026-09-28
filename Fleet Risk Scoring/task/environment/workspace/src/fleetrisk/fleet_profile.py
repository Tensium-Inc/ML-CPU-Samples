"""What the register says about the aircraft flying this leg."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add(df, fleet):
    reg = fleet.set_index("tail_number")
    operators = sorted(fleet["operator"].dropna().unique())
    codes = {name: float(i) for i, name in enumerate(operators)}
    sizes = fleet.groupby("operator")["tail_number"].nunique()

    out = df.copy()
    home = out["tail_number"].map(reg["home_station"])
    carrier = out["tail_number"].map(reg["operator"]).fillna(out["operator"])
    out["f_operator"] = carrier.map(codes).fillna(-1.0).astype("float64")
    out["f_from_home"] = (out["origin"] == home).astype("float64")
    out["f_fleet_size"] = carrier.map(sizes).fillna(0.0).astype("float64")
    return out
