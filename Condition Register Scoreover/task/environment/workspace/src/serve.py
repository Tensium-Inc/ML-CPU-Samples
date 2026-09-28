"""Turning a scored batch into the export the network receives."""
from __future__ import annotations

import pandas as pd

from . import features, register


def build_serving_frame(batch: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Feature frame for the encounters in `batch`."""
    return features.build_features(batch, cfg)


def scored_rows(batch: pd.DataFrame, scores: pd.Series, cfg: dict) -> pd.DataFrame:
    """The export: the score for each encounter alongside its condition register."""
    columns = list(cfg["scoring"]["output_columns"])
    reg = register.registers(batch, cfg)
    out = pd.DataFrame({"encounter_id": scores.index.astype("int64"),
                        "score": scores.astype(float).values})
    out = out.merge(reg, on="encounter_id", how="left")
    out = out.rename(columns={"code": "conditions"})
    return out.sort_values("encounter_id", kind="stable")[columns].reset_index(drop=True)
