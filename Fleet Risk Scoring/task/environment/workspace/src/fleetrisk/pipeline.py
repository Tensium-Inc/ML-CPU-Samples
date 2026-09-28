"""Fits on the fit window and scores the window the run config names."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import (assemble, calendar_feats, deviations, fleet_profile, io_layer,
               model, observation, portfolio, recent, reliability, route_feats,
               station_history, station_profile, tail_history)


def _window(df, spec):
    lo = pd.Timestamp(spec["from"])
    hi = pd.Timestamp(spec["to"]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return df[(df["departed_at"] >= lo) & (df["departed_at"] <= hi)]


def build(cfg):
    flights = io_layer.read_flights(cfg)
    groundings = io_layer.read_groundings(cfg)
    fleet = io_layer.read_fleet(cfg)
    stations = io_layer.read_stations(cfg)

    window_days = cfg["labelling"]["window_days"]
    export_end = flights["departed_at"].max()
    period_start = flights["departed_at"].min()

    labelled = observation.attach_label(flights, groundings, window_days)
    labelled = labelled.sort_values("flight_id", kind="stable").reset_index(drop=True)

    fit_raw = _window(labelled, cfg["windows"]["fit"])
    fit_raw = fit_raw[observation.observed(fit_raw, cfg["windows"]["fit"],
                                          export_end, window_days)]
    fit_raw = fit_raw.reset_index(drop=True)
    score_raw = _window(labelled, cfg["windows"]["score"]).reset_index(drop=True)

    fit_end = fit_raw["departed_at"].max()
    levels = portfolio.levels(fit_raw, groundings, fit_end)
    hist = tail_history.history(fit_raw, groundings, fit_end)

    def prepare(frame):
        out = calendar_feats.add(frame, period_start)
        out = route_feats.add(out)
        out = fleet_profile.add(out, fleet)
        out = station_profile.add(out, stations)
        out = tail_history.add(out, hist, levels)
        out = station_history.add(out, fit_raw, groundings, fleet, fit_end, levels)
        out = recent.add(out, fit_raw, groundings, fit_end, levels)
        return out

    fit_df = prepare(fit_raw)
    score_df = prepare(score_raw)

    smoothing = cfg["encoding"]["smoothing"]
    base = levels["rate"]
    operator_rates = reliability.rate_table(fit_df, "operator", smoothing, base)
    fit_df = fit_df.assign(_route=reliability.route_key(fit_df))
    score_df = score_df.assign(_route=reliability.route_key(score_df))
    route_rates = reliability.rate_table(fit_df, "_route", smoothing, base)
    station_rates = reliability.rate_table(fit_df, "origin", smoothing, base)

    fit_df = reliability.add(fit_df, operator_rates, route_rates, station_rates)
    score_df = reliability.add(score_df, operator_rates, route_rates, station_rates)
    fit_df = deviations.add(fit_df, levels)
    score_df = deviations.add(score_df, levels)
    return fit_df.drop(columns=["_route"]), score_df.drop(columns=["_route"])


def run(cfg):
    fit_df, score_df = build(cfg)

    mdl = model.RiskModel(cfg["model"]["seed"], cfg["model"]["max_iter"],
                          cfg["model"]["learning_rate"], cfg["model"]["max_depth"])
    mdl.fit(assemble.matrix(fit_df), fit_df["label"].astype("int64").to_numpy())

    risk = mdl.score(assemble.matrix(score_df))
    threshold = float(cfg["scoring"]["watch_threshold"])
    out = pd.DataFrame({
        "flight_id": score_df["flight_id"].astype(str).to_numpy(),
        "tail_number": score_df["tail_number"].astype(str).to_numpy(),
        "departed_at": score_df["departed_at"].to_numpy(),
        "risk_score": np.round(risk, 6),
        "watch": (risk >= threshold).astype("int64"),
    })
    return out, fit_df, score_df
