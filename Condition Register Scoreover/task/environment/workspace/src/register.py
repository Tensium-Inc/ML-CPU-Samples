"""The condition register that rides alongside every score.

Held in long form, one row per (encounter_id, code), because that is the grain the downstream
refresh job writes and the grain the feature builder counts. `config.yaml` names the index the
refresh job delivers and the columns the charted codes sit in.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import codes

ROOT = Path(__file__).resolve().parent.parent
EVENT_COLUMNS = ["encounter_id", "patient_nbr", "code"]
INDEX_COLUMNS = ["patient_nbr", "code"]


def load_index(cfg: dict) -> pd.DataFrame:
    """The condition index the refresh job delivers, one row per (patient, code)."""
    path = ROOT / cfg["register"]["index"]
    frame = pd.read_csv(path, dtype={"code": str})
    return frame[INDEX_COLUMNS].astype({"patient_nbr": "int64"}).drop_duplicates()


def load_code_table(cfg: dict) -> pd.Series:
    """The code table the register is keyed on: charted code -> register code."""
    path = ROOT / cfg["register"]["code_table"]
    frame = pd.read_csv(path, dtype=str)
    return frame.set_index("charted_code")["register_code"]


def condition_events(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """One row per (encounter_id, patient_nbr, code) charted on the encounter itself."""
    policy = cfg["register"]
    long = encounters.melt(id_vars=["encounter_id", "patient_nbr"],
                           value_vars=list(policy["code_columns"]),
                           var_name="field", value_name="raw")
    charted = codes.normalise(long["raw"], policy.get("missing_marker", "?"))
    table = load_code_table(cfg)
    long["code"] = charted.map(table).fillna(charted)
    long = long.dropna(subset=["code"]).astype({"encounter_id": "int64", "patient_nbr": "int64"})
    return long[EVENT_COLUMNS].drop_duplicates()


def registers(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """The condition register for every encounter in `encounters`, in long form.

    What the encounter charts, together with what the index already holds for that patient.
    One row per (encounter_id, code), distinct codes only, in a stable order.
    """
    charted = condition_events(encounters, cfg)
    keys = (encounters[["encounter_id", "patient_nbr"]]
            .astype({"encounter_id": "int64", "patient_nbr": "int64"})
            .drop_duplicates())
    on_file = keys.merge(load_index(cfg), on="patient_nbr", how="inner")[EVENT_COLUMNS]
    return (pd.concat([charted, on_file], ignore_index=True)[["encounter_id", "code"]]
            .drop_duplicates()
            .sort_values(["encounter_id", "code"], kind="stable")
            .reset_index(drop=True))


def sizes(encounters: pd.DataFrame, cfg: dict) -> pd.Series:
    """How many conditions each encounter's register holds, indexed by encounter id."""
    reg = registers(encounters, cfg)
    counts = reg.groupby("encounter_id")["code"].size()
    index = encounters["encounter_id"].astype("int64")
    return counts.reindex(index).fillna(0).astype(float).set_axis(index)
