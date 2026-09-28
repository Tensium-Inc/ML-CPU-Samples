"""Per-encounter feature construction."""
from __future__ import annotations

import pandas as pd

from . import register

ENCOUNTER_COLUMNS = [
    "time_in_hospital", "num_lab_procedures", "num_procedures", "num_medications",
    "number_outpatient", "number_emergency", "number_inpatient", "number_diagnoses",
]
FEATURE_COLUMNS = ENCOUNTER_COLUMNS + ["n_conditions"]


def prepare(encounters: pd.DataFrame) -> pd.DataFrame:
    """Normalise a raw encounter extract into the frame the pipeline works on."""
    frame = encounters.copy()
    frame["encounter_id"] = frame["encounter_id"].astype("int64")
    frame["patient_nbr"] = frame["patient_nbr"].astype("int64")
    return frame.set_index("encounter_id", drop=False)


def build_features(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Feature frame for every encounter in `encounters`, indexed by encounter id."""
    frame = prepare(encounters)
    out = frame[ENCOUNTER_COLUMNS].astype(float)
    out["n_conditions"] = register.sizes(frame, cfg).values
    return out[FEATURE_COLUMNS].sort_index()


def build_labels(encounters: pd.DataFrame) -> pd.Series:
    """1 if the encounter was followed by a readmission inside the horizon."""
    frame = prepare(encounters)
    return (frame["readmitted"] == "<30").astype(int).sort_index().rename("label")
