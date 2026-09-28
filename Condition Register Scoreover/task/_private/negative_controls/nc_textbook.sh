#!/usr/bin/env bash
# The familiar one-line fix: group by patient and union the lot. It is the best configuration on
# every number the agent can compute for itself, it passes the smoke tests, it drives the whole
# walk, and it puts conditions on a register before they were recorded. Must score 0, and it
# must get all the way to the TERMINAL to do it.
set -euo pipefail
. "$(dirname "$0")/_arm.sh"
cat > "$ARM/register.py" <<'REG_EOF'
"""The condition register that rides alongside every score."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import codes

ROOT = Path(__file__).resolve().parent.parent
KEY_COLUMNS = ["encounter_id", "patient_nbr"]


def _visible(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    columns = KEY_COLUMNS + list(cfg["register"]["code_columns"])
    archive = pd.read_csv(ROOT / cfg["paths"]["encounters"], low_memory=False)
    both = pd.concat([archive[columns], encounters[columns]], ignore_index=True)
    both = both.astype({"encounter_id": "int64", "patient_nbr": "int64"})
    return both.drop_duplicates(subset=["encounter_id"])


def condition_events(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    policy = cfg["register"]
    long = encounters.melt(id_vars=KEY_COLUMNS, value_vars=list(policy["code_columns"]),
                           var_name="field", value_name="raw")
    long["code"] = codes.normalise(long["raw"], policy.get("missing_marker", "?"))
    long = long.dropna(subset=["code"])
    return long[["encounter_id", "patient_nbr", "code"]].drop_duplicates()


def registers(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Everything on file for the patient, attached to each of their encounters."""
    wanted = encounters["encounter_id"].astype("int64")
    visible = _visible(encounters, cfg)
    events = condition_events(visible, cfg)
    per_patient = events[["patient_nbr", "code"]].drop_duplicates()
    here = visible.loc[visible["encounter_id"].isin(set(wanted)), KEY_COLUMNS]
    out = (here.merge(per_patient, on="patient_nbr", how="left")
           .dropna(subset=["code"])[["encounter_id", "code"]]
           .drop_duplicates()
           .sort_values(["encounter_id", "code"], kind="stable")
           .reset_index(drop=True))
    return out


def sizes(encounters: pd.DataFrame, cfg: dict) -> pd.Series:
    index = encounters["encounter_id"].astype("int64")
    counted = registers(encounters, cfg).groupby("encounter_id")["code"].nunique()
    return counted.reindex(index).fillna(0).astype(float).set_axis(index)
REG_EOF
export FIX_DIR="$ARM"
source "$(dirname "$0")/_drive_full.sh"
