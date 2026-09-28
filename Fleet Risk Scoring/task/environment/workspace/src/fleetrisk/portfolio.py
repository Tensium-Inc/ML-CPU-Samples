"""Fleet-wide levels, used wherever a row has no history of its own."""
from __future__ import annotations

import numpy as np
import pandas as pd


def levels(fit_flights, groundings, fit_end):
    """One fallback number per quantity, taken over the whole fit window."""
    seen = groundings[groundings["occurred_at"] <= pd.Timestamp(fit_end)]
    per_tail = fit_flights.groupby("tail_number").agg(
        flights=("flight_id", "size"), first_seen=("departed_at", "min"),
        last_seen=("departed_at", "max"))
    tenure = (pd.Timestamp(fit_end) - per_tail["first_seen"]).dt.total_seconds() / 86400.0
    gap = (pd.Timestamp(fit_end) - per_tail["last_seen"]).dt.total_seconds() / 86400.0
    return {
        "rate": float(len(seen)) / max(float(len(fit_flights)), 1.0),
        "tenure": float(tenure.mean()),
        "gap": float(gap.mean()),
        "dep_delay": float(pd.to_numeric(fit_flights["departure_delay"],
                                         errors="coerce").mean()),
    }
