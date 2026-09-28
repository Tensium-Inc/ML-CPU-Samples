#!/usr/bin/env bash
# SECOND alternate-correct solution: a third independent implementation.
#
# Labels are resolved per aircraft over contiguous runs of a sorted key rather than
# row by row, the observation cut is expressed as the window closing on or before the
# export, rate tables are accumulated through an explicit code map, and recent form
# is taken from a reverse cumulative count rather than a tail slice.
set -euo pipefail

cd /workspace/target

cat > src/fleetrisk/observation.py <<'FLEETRISK_EOF'
"""Which flights carry an outcome the export can actually show.

The risk a flight is scored for is settled by what happens to that aircraft over the
days that follow it. A flight near the end of that history has not had those days yet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def attach_label(flights, groundings, window_days):
    """A flight is at risk if its aircraft is grounded within the labelling window."""
    span = np.timedelta64(int(float(window_days) * 86400), "s")
    out = flights.copy()
    label = np.zeros(len(out), dtype="int64")

    tails = out["tail_number"].to_numpy()
    starts = out["departed_at"].to_numpy()
    order = np.argsort(tails, kind="stable")

    stops = {}
    for tail, group in groundings.groupby("tail_number", sort=False):
        stops[tail] = np.sort(group["occurred_at"].to_numpy())

    position = 0
    while position < len(order):
        run = position
        tail = tails[order[position]]
        while run < len(order) and tails[order[run]] == tail:
            run += 1
        arrivals = stops.get(tail)
        if arrivals is not None:
            rows = order[position:run]
            begin = starts[rows]
            lo = np.searchsorted(arrivals, begin, side="right")
            hi = np.searchsorted(arrivals, begin + span, side="right")
            label[rows] = (hi > lo).astype("int64")
        position = run

    out["label"] = label
    return out


def observed(df, fit_spec, export_end, window_days):
    """The rows whose labelling window closes inside the history the run may read."""
    day = pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    bound = min(pd.Timestamp(fit_spec["to"]) + day, pd.Timestamp(export_end))
    closes = df["departed_at"] + pd.Timedelta(days=float(window_days))
    return closes <= bound
FLEETRISK_EOF

cat > src/fleetrisk/recent.py <<'FLEETRISK_EOF'
"""How the aircraft has been behaving lately, rather than over the whole window."""
from __future__ import annotations

import numpy as np
import pandas as pd

RECENT_FLIGHTS = 20


def add(df, fit_flights, groundings, fit_end, portfolio):
    end = pd.Timestamp(fit_end)
    start = end - pd.Timedelta(days=14)

    ordered = fit_flights.sort_values(["tail_number", "departed_at"], kind="stable")
    rank = ordered.groupby("tail_number").cumcount(ascending=False)
    tail_slice = ordered[rank < RECENT_FLIGHTS]
    recent_delay = tail_slice.groupby("tail_number")["departure_delay"].mean()
    last_flight = ordered.groupby("tail_number")["departed_at"].last()

    window = ordered[ordered["departed_at"] > start]
    flown = window.groupby("tail_number").size()
    stopped = (groundings[(groundings["occurred_at"] > start)
                          & (groundings["occurred_at"] <= end)]
               .groupby("tail_number").size())

    out = df.copy()
    keys = out["tail_number"]
    counted = keys.map(flown).fillna(0.0).astype("float64")
    hit = keys.map(stopped).fillna(0.0).astype("float64")
    rate = np.divide(hit.to_numpy(), np.maximum(counted.to_numpy(), 1.0))
    rate = np.where(counted.to_numpy() > 0, rate, np.nan)
    out["f_recent_grounding_rate"] = pd.Series(rate, index=out.index).fillna(
        portfolio["rate"]).astype("float64")
    gap = (end - keys.map(last_flight)).dt.total_seconds() / 86400.0
    out["f_days_since_prev_flight"] = gap.fillna(portfolio["gap"]).astype("float64")
    out["f_recent_dep_delay"] = keys.map(recent_delay).fillna(
        portfolio["dep_delay"]).astype("float64")
    return out
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
    keys = fit_df[key].to_numpy()
    labels = fit_df["label"].to_numpy(dtype="float64")
    seen = {}
    hits = []
    counts = []
    index = np.empty(len(keys), dtype="int64")
    for position, value in enumerate(keys):
        slot = seen.get(value)
        if slot is None:
            slot = len(counts)
            seen[value] = slot
            counts.append(0.0)
            hits.append(0.0)
        index[position] = slot
    counts = np.bincount(index, minlength=len(counts)).astype("float64")
    hits = np.bincount(index, weights=labels, minlength=len(counts)).astype("float64")
    s = float(smoothing)
    values = (hits + s * float(prior)) / (counts + s)
    table = pd.Series(values, index=pd.Index(sorted(seen, key=seen.get)), dtype="float64")
    table[CATCH_ALL] = float(prior)
    return table


def route_key(df):
    return df["origin"].astype(str) + ">" + df["destination"].astype(str)


def add(df, operator_rates, route_rates, station_rates):
    out = df.copy()
    for column, keys, table in (
        ("f_operator_rate", out["operator"].astype(str), operator_rates),
        ("f_route_rate", route_key(out), route_rates),
        ("f_station_rate", out["origin"].astype(str), station_rates),
    ):
        known = table.index
        masked = keys.where(keys.isin(known), CATCH_ALL)
        out[column] = masked.map(table).astype("float64")
    return out
FLEETRISK_EOF

cat > src/fleetrisk/station_history.py <<'FLEETRISK_EOF'
"""What the fit window knows about the airports at each end."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add(df, fit_flights, groundings, fleet, fit_end, portfolio):
    seen = groundings[groundings["occurred_at"] <= pd.Timestamp(fit_end)]
    home = fleet.set_index("tail_number")["home_station"]
    stop_station = seen["tail_number"].map(home)
    stops = stop_station.value_counts()
    flown = fit_flights["origin"].value_counts()

    out = df.copy()
    for side, column in (("origin", "f_origin"), ("destination", "f_dest")):
        keys = out[side]
        count = keys.map(flown).fillna(0.0).astype("float64")
        grounded = keys.map(stops).fillna(0.0).astype("float64")
        out[column + "_prior_flights"] = count
        rate = np.where(count > 0, grounded / count.clip(lower=1.0), np.nan)
        out[column + "_grounding_rate"] = pd.Series(rate, index=out.index).fillna(
            portfolio["rate"]).astype("float64")
    return out
FLEETRISK_EOF

cat > src/fleetrisk/tail_history.py <<'FLEETRISK_EOF'
"""What the fit window knows about the aircraft."""
from __future__ import annotations

import numpy as np
import pandas as pd


def history(fit_flights, groundings, fit_end):
    """Per aircraft: how much it flew, how often it was grounded, and how recently."""
    flown = fit_flights.groupby("tail_number").agg(
        flights=("flight_id", "size"),
        first_seen=("departed_at", "min"),
        mean_dep_delay=("departure_delay", "mean"),
    )
    seen = groundings[groundings["occurred_at"] <= pd.Timestamp(fit_end)]
    stops = seen.groupby("tail_number").agg(
        groundings=("occurred_at", "size"),
        last_grounding=("occurred_at", "max"),
    )
    joined = flown.join(stops, how="left")
    joined["groundings"] = joined["groundings"].fillna(0.0)
    joined["tenure_days"] = ((pd.Timestamp(fit_end) - joined["first_seen"])
                             .dt.total_seconds() / 86400.0)
    joined["days_since_grounding"] = ((pd.Timestamp(fit_end) - joined["last_grounding"])
                                      .dt.total_seconds() / 86400.0)
    joined["rate"] = joined["groundings"] / joined["flights"].clip(lower=1.0)
    return joined


def add(df, hist, portfolio):
    out = df.copy()
    keys = out["tail_number"]
    out["f_tail_prior_flights"] = keys.map(hist["flights"]).fillna(0.0).astype("float64")
    out["f_tail_prior_groundings"] = keys.map(hist["groundings"]).fillna(0.0).astype("float64")
    out["f_tail_grounding_rate"] = (keys.map(hist["rate"])
                                    .fillna(portfolio["rate"]).astype("float64"))
    out["f_tail_days_since_grounding"] = (keys.map(hist["days_since_grounding"])
                                          .fillna(-1.0).astype("float64"))
    out["f_tail_tenure_days"] = (keys.map(hist["tenure_days"])
                                 .fillna(portfolio["tenure"]).astype("float64"))
    out["f_tail_mean_dep_delay"] = (keys.map(hist["mean_dep_delay"])
                                    .fillna(portfolio["dep_delay"]).astype("float64"))
    return out
FLEETRISK_EOF

python3 run_scoring.py --config configs/reference.yaml --out out/reference
python3 run_scoring.py --config configs/current.yaml   --out out/current
echo "rebuild complete"
