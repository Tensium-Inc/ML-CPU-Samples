#!/usr/bin/env bash
# PERTURBED gold: locals renamed throughout, nothing else changed.
# An incidental change must still reproduce the published run exactly.
set -euo pipefail

cd /workspace/target

cat > src/fleetrisk/observation.py <<'FLEETRISK_EOF'
"""Labelling, and the subset of the export the desk fits on."""
from __future__ import annotations

import numpy as np
import pandas as pd


def attach_label(flights, groundings, window_days):
    stops = {tail: np.sort(group["occurred_at"].to_numpy())
              for tail, group in groundings.groupby("tail_number", sort=False)}
    frame = flights.copy()
    flags = np.zeros(len(frame), dtype="int64")
    registrations = frame["tail_number"].to_numpy()
    starts = frame["departed_at"].to_numpy()
    for row in range(len(frame)):
        marks = stops.get(registrations[row])
        if marks is None:
            continue
        begin = np.datetime64(starts[row])
        until = begin + np.timedelta64(int(window_days * 24 * 3600), "s")
        first = np.searchsorted(marks, begin, side="right")
        last = np.searchsorted(marks, until, side="right")
        if last > first:
            flags[row] = 1
    frame["label"] = flags
    return frame


def observed(df, fit_spec, export_end, window_days):
    span = pd.Timedelta(days=float(window_days))
    cutoff = pd.Timestamp(fit_spec["to"]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return df["departed_at"] <= (min(cutoff, pd.Timestamp(export_end)) - span)
FLEETRISK_EOF

cat > src/fleetrisk/recent.py <<'FLEETRISK_EOF'
"""How the aircraft has been behaving lately, rather than over the whole window."""
from __future__ import annotations

import numpy as np
import pandas as pd

RECENT_FLIGHTS = 20


def add(df, fit_flights, groundings, fit_end, portfolio):
    sorted_legs = fit_flights.sort_values(["tail_number", "departed_at"], kind="stable")
    last_legs = sorted_legs.groupby("tail_number").tail(RECENT_FLIGHTS)
    recent_delay = last_legs.groupby("tail_number")["departure_delay"].mean()
    last_flight = sorted_legs.groupby("tail_number")["departed_at"].max()

    since = pd.Timestamp(fit_end) - pd.Timedelta(days=14)
    halts = groundings[(groundings["occurred_at"] > since)
                      & (groundings["occurred_at"] <= pd.Timestamp(fit_end))]
    late_counts = halts["tail_number"].value_counts()
    flights_in_window = (sorted_legs[sorted_legs["departed_at"] > since]
                         ["tail_number"].value_counts())

    frame = df.copy()
    registrations = frame["tail_number"]
    flew = registrations.map(flights_in_window).fillna(0.0).astype("float64")
    halted = registrations.map(late_counts).fillna(0.0).astype("float64")
    share = np.where(flew > 0, halted / flew.clip(lower=1.0), np.nan)
    frame["f_recent_grounding_rate"] = pd.Series(share, index=frame.index).fillna(
        portfolio["rate"]).astype("float64")
    idle = (pd.Timestamp(fit_end) - registrations.map(last_flight)).dt.total_seconds() / 86400.0
    frame["f_days_since_prev_flight"] = idle.fillna(portfolio["gap"]).astype("float64")
    frame["f_recent_dep_delay"] = (registrations.map(recent_delay)
                                 .fillna(portfolio["dep_delay"]).astype("float64"))
    return frame
FLEETRISK_EOF

cat > src/fleetrisk/reliability.py <<'FLEETRISK_EOF'
"""Grounding rates by operator, by route and by station.

A rate over thin history says more about the thinness than about the risk, so each one
is pulled toward the portfolio rate in proportion to how little stands behind it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CATCH_ALL = "__unseen__"


def rate_table(fit_df, key, smoothing, prior):
    buckets = fit_df.groupby(key)["label"]
    summary = buckets.agg(["count", "mean"])
    pull = summary["count"] / (summary["count"] + float(smoothing))
    blended = pull * summary["mean"] + (1.0 - pull) * float(prior)
    spare = pd.Series({CATCH_ALL: float(prior)}, dtype="float64")
    return pd.concat([blended.astype("float64"), spare])


def route_key(df):
    return df["origin"].astype(str) + ">" + df["destination"].astype(str)


def add(df, operator_rates, route_rates, station_rates):
    frame = df.copy()
    for name, codes, lookup in (
        ("f_operator_rate", frame["operator"].astype(str), operator_rates),
        ("f_route_rate", route_key(frame), route_rates),
        ("f_station_rate", frame["origin"].astype(str), station_rates),
    ):
        codes = codes.where(codes.isin(lookup.index), CATCH_ALL)
        frame[name] = codes.map(lookup).astype("float64")
    return frame
FLEETRISK_EOF

cat > src/fleetrisk/station_history.py <<'FLEETRISK_EOF'
"""What the fit window knows about the airports at each end."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add(df, fit_flights, groundings, fleet, fit_end, portfolio):
    known = groundings[groundings["occurred_at"] <= pd.Timestamp(fit_end)]
    based_at = fleet.set_index("tail_number")["home_station"]
    at = known["tail_number"].map(based_at)
    halts = at.value_counts()
    departures = fit_flights["origin"].value_counts()

    frame = df.copy()
    for side, column in (("origin", "f_origin"), ("destination", "f_dest")):
        codes = frame[side]
        total = codes.map(departures).fillna(0.0).astype("float64")
        halted = codes.map(halts).fillna(0.0).astype("float64")
        frame[column + "_prior_flights"] = total
        share = np.where(total > 0, halted / total.clip(lower=1.0), np.nan)
        frame[column + "_grounding_rate"] = pd.Series(share, index=frame.index).fillna(
            portfolio["rate"]).astype("float64")
    return frame
FLEETRISK_EOF

cat > src/fleetrisk/tail_history.py <<'FLEETRISK_EOF'
"""What the fit window knows about the aircraft."""
from __future__ import annotations

import numpy as np
import pandas as pd


def history(fit_flights, groundings, fit_end):
    """Per aircraft: how much it flew, how often it was grounded, and how recently."""
    activity = fit_flights.groupby("tail_number").agg(
        flights=("flight_id", "size"),
        first_seen=("departed_at", "min"),
        mean_dep_delay=("departure_delay", "mean"),
    )
    known = groundings[groundings["occurred_at"] <= pd.Timestamp(fit_end)]
    halts = known.groupby("tail_number").agg(
        groundings=("occurred_at", "size"),
        last_grounding=("occurred_at", "max"),
    )
    merged = activity.join(halts, how="left")
    merged["groundings"] = merged["groundings"].fillna(0.0)
    merged["tenure_days"] = ((pd.Timestamp(fit_end) - merged["first_seen"])
                             .dt.total_seconds() / 86400.0)
    merged["days_since_grounding"] = ((pd.Timestamp(fit_end) - merged["last_grounding"])
                                      .dt.total_seconds() / 86400.0)
    merged["rate"] = merged["groundings"] / merged["flights"].clip(lower=1.0)
    return merged


def add(df, hist, portfolio):
    frame = df.copy()
    registrations = frame["tail_number"]
    frame["f_tail_prior_flights"] = registrations.map(hist["flights"]).fillna(0.0).astype("float64")
    frame["f_tail_prior_groundings"] = registrations.map(hist["groundings"]).fillna(0.0).astype("float64")
    frame["f_tail_grounding_rate"] = (registrations.map(hist["rate"])
                                    .fillna(portfolio["rate"]).astype("float64"))
    frame["f_tail_days_since_grounding"] = (registrations.map(hist["days_since_grounding"])
                                          .fillna(-1.0).astype("float64"))
    frame["f_tail_tenure_days"] = (registrations.map(hist["tenure_days"])
                                 .fillna(portfolio["tenure"]).astype("float64"))
    frame["f_tail_mean_dep_delay"] = (registrations.map(hist["mean_dep_delay"])
                                    .fillna(portfolio["dep_delay"]).astype("float64"))
    return frame
FLEETRISK_EOF

python3 run_scoring.py --config configs/reference.yaml --out out/reference
python3 run_scoring.py --config configs/current.yaml   --out out/current
echo "rebuild complete"
