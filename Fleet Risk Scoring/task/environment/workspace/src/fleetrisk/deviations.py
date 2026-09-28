"""How this aircraft, station and operator sit against the fleet as a whole."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add(df, portfolio):
    out = df.copy()
    base = float(portfolio["rate"])
    out["f_tail_vs_portfolio"] = (out["f_tail_grounding_rate"] - base).astype("float64")
    out["f_origin_vs_portfolio"] = (out["f_origin_grounding_rate"] - base).astype("float64")
    out["f_operator_vs_portfolio"] = (out["f_operator_rate"] - base).astype("float64")
    return out
