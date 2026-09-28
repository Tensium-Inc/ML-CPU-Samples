"""Grounding rates by operator, by route and by station.

A rate over thin history says more about the thinness than about the risk, so each one
is pulled toward the portfolio rate in proportion to how little stands behind it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CATCH_ALL = "__unseen__"


def rate_table(fit_df, key, smoothing, prior):
    raise NotImplementedError


def route_key(df):
    raise NotImplementedError


def add(df, operator_rates, route_rates, station_rates):
    raise NotImplementedError
