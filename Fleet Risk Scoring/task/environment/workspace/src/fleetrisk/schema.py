"""Column names and the published feature order."""
from __future__ import annotations

from typing import List

FLIGHT_ID = "flight_id"
TAIL = "tail_number"
DEPARTED = "departed_at"
LABEL = "label"

FEATURES: List[str] = [
    "f_hour", "f_dow", "f_month", "f_week", "f_is_weekend", "f_days_into_period",
    "f_distance", "f_block_minutes", "f_taxi_out", "f_departure_delay",
    "f_arrival_delay", "f_diverted", "f_block_speed",
    "f_operator", "f_from_home", "f_fleet_size",
    "f_origin_state", "f_dest_state", "f_same_state",
    "f_tail_prior_flights", "f_tail_prior_groundings", "f_tail_grounding_rate",
    "f_tail_days_since_grounding", "f_tail_tenure_days", "f_tail_mean_dep_delay",
    "f_origin_prior_flights", "f_origin_grounding_rate",
    "f_dest_prior_flights", "f_dest_grounding_rate",
    "f_operator_rate", "f_route_rate", "f_station_rate",
    "f_recent_grounding_rate", "f_days_since_prev_flight", "f_recent_dep_delay",
    "f_tail_vs_portfolio", "f_origin_vs_portfolio", "f_operator_vs_portfolio",
]


def drop_label(df):
    return df.drop(columns=[LABEL], errors="ignore")
