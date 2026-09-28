"""Reads the nightly operations export."""
from __future__ import annotations

import pandas as pd

try:
    from .config import data_path
except ImportError:
    from config import data_path


def read_flights(cfg):
    df = pd.read_csv(data_path("flights.csv.gz", cfg), parse_dates=["departed_at"])
    return df.sort_values("flight_id", kind="stable").reset_index(drop=True)


def read_groundings(cfg):
    df = pd.read_csv(data_path("groundings.csv.gz", cfg), parse_dates=["occurred_at"])
    return df.sort_values(["occurred_at", "tail_number"], kind="stable").reset_index(drop=True)


def read_fleet(cfg):
    return pd.read_csv(data_path("fleet.csv", cfg))


def read_stations(cfg):
    return pd.read_csv(data_path("stations.csv", cfg))
