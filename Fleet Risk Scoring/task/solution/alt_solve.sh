#!/usr/bin/env bash
# ALTERNATE-correct solution: the same specification implemented differently.
#
# The label comes from a forward merge_asof against the grounding feed rather than a
# per-aircraft search, the observation cut is expressed on the departure side, rates
# are blended as sums over counts, and the aircraft record is accumulated with
# bincount over factorised tails instead of a groupby.
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
    horizon = pd.Timedelta(days=float(window_days))
    out = flights.copy()
    if groundings.empty:
        out["label"] = np.zeros(len(out), dtype="int64")
        return out

    stops = (groundings[["tail_number", "occurred_at"]]
             .sort_values("occurred_at", kind="stable"))
    probe = (out[["tail_number", "departed_at"]].assign(_pos=np.arange(len(out)))
             .sort_values("departed_at", kind="stable"))

    next_stop = pd.merge_asof(
        probe, stops.rename(columns={"occurred_at": "_stop"}),
        left_on="departed_at", right_on="_stop", by="tail_number",
        direction="forward", allow_exact_matches=False)
    next_stop = next_stop.sort_values("_pos", kind="stable")
    gap = next_stop["_stop"].to_numpy() - next_stop["departed_at"].to_numpy()
    within = np.zeros(len(out), dtype="int64")
    valid = ~pd.isna(next_stop["_stop"].to_numpy())
    within[valid] = (gap[valid] <= np.timedelta64(horizon)).astype("int64")
    out["label"] = within
    return out


def observed(df, fit_spec, export_end, window_days):
    """The rows whose labelling window closes inside the history the run may read."""
    edge = pd.Timestamp(fit_spec["to"]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    latest = min(edge, pd.Timestamp(export_end)) - pd.Timedelta(days=float(window_days))
    return pd.Series(df["departed_at"].to_numpy() <= np.datetime64(latest),
                     index=df.index)
FLEETRISK_EOF

cat > src/fleetrisk/recent.py <<'FLEETRISK_EOF'
"""How the aircraft has been behaving lately, rather than over the whole window."""
from __future__ import annotations

import numpy as np
import pandas as pd

RECENT_FLIGHTS = 20


def add(df, fit_flights, groundings, fit_end, portfolio):
    ordered = fit_flights.sort_values(["tail_number", "departed_at"], kind="stable")
    tail = ordered.groupby("tail_number").tail(RECENT_FLIGHTS)
    recent_delay = tail.groupby("tail_number")["departure_delay"].mean()
    last_flight = ordered.groupby("tail_number")["departed_at"].max()

    window_start = pd.Timestamp(fit_end) - pd.Timedelta(days=14)
    late = groundings[(groundings["occurred_at"] > window_start)
                      & (groundings["occurred_at"] <= pd.Timestamp(fit_end))]
    late_counts = late["tail_number"].value_counts()
    flights_in_window = (ordered[ordered["departed_at"] > window_start]
                         ["tail_number"].value_counts())

    out = df.copy()
    keys = out["tail_number"]
    counted = keys.map(flights_in_window).fillna(0.0).astype("float64")
    stopped = keys.map(late_counts).fillna(0.0).astype("float64")
    rate = np.where(counted > 0, stopped / counted.clip(lower=1.0), np.nan)
    out["f_recent_grounding_rate"] = pd.Series(rate, index=out.index).fillna(
        portfolio["rate"]).astype("float64")
    gap = (pd.Timestamp(fit_end) - keys.map(last_flight)).dt.total_seconds() / 86400.0
    out["f_days_since_prev_flight"] = gap.fillna(portfolio["gap"]).astype("float64")
    out["f_recent_dep_delay"] = (keys.map(recent_delay)
                                 .fillna(portfolio["dep_delay"]).astype("float64"))
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
    counts = fit_df.groupby(key)["label"].size().astype("float64")
    totals = fit_df.groupby(key)["label"].sum().astype("float64")
    smoothing = float(smoothing)
    blended = (totals + smoothing * float(prior)) / (counts + smoothing)
    blended[CATCH_ALL] = float(prior)
    return blended.astype("float64")


def route_key(df):
    return df["origin"].astype(str) + ">" + df["destination"].astype(str)


def add(df, operator_rates, route_rates, station_rates):
    out = df.copy()
    plans = (("f_operator_rate", out["operator"].astype(str), operator_rates),
             ("f_route_rate", route_key(out), route_rates),
             ("f_station_rate", out["origin"].astype(str), station_rates))
    for column, keys, table in plans:
        lookup = table.to_dict()
        default = lookup[CATCH_ALL]
        out[column] = np.array([lookup.get(k, default) for k in keys], dtype="float64")
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
    end = pd.Timestamp(fit_end)
    tails = fit_flights["tail_number"].to_numpy()
    order = pd.Index(pd.unique(tails))
    code = pd.Series(np.arange(len(order)), index=order)
    idx = code.reindex(tails).to_numpy()

    flights = np.bincount(idx, minlength=len(order)).astype("float64")
    delays = pd.to_numeric(fit_flights["departure_delay"], errors="coerce").fillna(0.0)
    delay_sum = np.bincount(idx, weights=delays.to_numpy(), minlength=len(order))
    first_seen = fit_flights.groupby("tail_number")["departed_at"].min().reindex(order)

    seen = groundings[groundings["occurred_at"] <= end]
    stop_count = seen["tail_number"].value_counts().reindex(order).fillna(0.0)
    last_stop = seen.groupby("tail_number")["occurred_at"].max().reindex(order)

    frame = pd.DataFrame(index=order)
    frame["flights"] = flights
    frame["groundings"] = stop_count.to_numpy()
    frame["mean_dep_delay"] = delay_sum / np.maximum(flights, 1.0)
    frame["tenure_days"] = (end - first_seen).dt.total_seconds() / 86400.0
    frame["days_since_grounding"] = (end - last_stop).dt.total_seconds() / 86400.0
    frame["rate"] = frame["groundings"] / np.maximum(frame["flights"], 1.0)
    frame.index.name = "tail_number"
    return frame


def add(df, hist, portfolio):
    out = df.copy()
    keys = out["tail_number"]
    pick = lambda column: keys.map(hist[column])
    out["f_tail_prior_flights"] = pick("flights").fillna(0.0).astype("float64")
    out["f_tail_prior_groundings"] = pick("groundings").fillna(0.0).astype("float64")
    out["f_tail_grounding_rate"] = pick("rate").fillna(portfolio["rate"]).astype("float64")
    out["f_tail_days_since_grounding"] = pick("days_since_grounding").fillna(-1.0).astype("float64")
    out["f_tail_tenure_days"] = pick("tenure_days").fillna(portfolio["tenure"]).astype("float64")
    out["f_tail_mean_dep_delay"] = pick("mean_dep_delay").fillna(portfolio["dep_delay"]).astype("float64")
    return out
FLEETRISK_EOF

python3 run_scoring.py --config configs/reference.yaml --out out/reference
python3 run_scoring.py --config configs/current.yaml   --out out/current
echo "rebuild complete"
