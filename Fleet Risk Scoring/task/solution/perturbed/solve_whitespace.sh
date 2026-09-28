#!/usr/bin/env bash
# PERTURBED gold: blank lines added between statements, nothing else changed.
# An incidental change must still reproduce the published run exactly.
set -euo pipefail

cd /workspace/target

cat > src/fleetrisk/observation.py <<'FLEETRISK_EOF'
"""Labelling, and the subset of the export the desk fits on."""

from __future__ import annotations

import numpy as np

import pandas as pd


def attach_label(flights, groundings, window_days):
    events = {tail: np.sort(group["occurred_at"].to_numpy())
              for tail, group in groundings.groupby("tail_number", sort=False)}

    out = flights.copy()

    label = np.zeros(len(out), dtype="int64")

    tails = out["tail_number"].to_numpy()

    when = out["departed_at"].to_numpy()

    for position in range(len(out)):
        arrivals = events.get(tails[position])

        if arrivals is None:
            continue

        start = np.datetime64(when[position])

        stop = start + np.timedelta64(int(window_days * 24 * 3600), "s")

        lo = np.searchsorted(arrivals, start, side="right")

        hi = np.searchsorted(arrivals, stop, side="right")

        if hi > lo:
            label[position] = 1

    out["label"] = label

    return out


def observed(df, fit_spec, export_end, window_days):
    horizon = pd.Timedelta(days=float(window_days))

    edge = pd.Timestamp(fit_spec["to"]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    return df["departed_at"] <= (min(edge, pd.Timestamp(export_end)) - horizon)
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
    grouped = fit_df.groupby(key)["label"]

    stats = grouped.agg(["count", "mean"])

    weight = stats["count"] / (stats["count"] + float(smoothing))

    rates = weight * stats["mean"] + (1.0 - weight) * float(prior)

    catch_all = pd.Series({CATCH_ALL: float(prior)}, dtype="float64")

    return pd.concat([rates.astype("float64"), catch_all])


def route_key(df):
    return df["origin"].astype(str) + ">" + df["destination"].astype(str)


def add(df, operator_rates, route_rates, station_rates):
    out = df.copy()

    for column, keys, table in (
        ("f_operator_rate", out["operator"].astype(str), operator_rates),
        ("f_route_rate", route_key(out), route_rates),
        ("f_station_rate", out["origin"].astype(str), station_rates),
    ):
        keys = keys.where(keys.isin(table.index), CATCH_ALL)

        out[column] = keys.map(table).astype("float64")

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
