#!/usr/bin/env bash
# Correct as-of logic, but the archive's codes are memoised into var/ on first run and reused
# blind afterwards. The cache rides along in every staged run, so the release stops tracking its
# own input. Must floor when the terminal cuts the archive short underneath it. This is the
# control that keeps the archive clause measured rather than asserted.
set -euo pipefail
. "$(dirname "$0")/_arm.sh"
cat > "$ARM/register.py" <<'REG_EOF'
"""The condition register that rides alongside every score."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import codes

ROOT = Path(__file__).resolve().parent.parent
EVENT_COLUMNS = ["encounter_id", "patient_nbr", "code"]
KEY_COLUMNS = ["encounter_id", "patient_nbr"]
CACHE = ROOT / "var" / "archive_cache.csv"


def load_archive(cfg: dict) -> pd.DataFrame:
    """The encounter history, memoised so repeated calls do not re-read a large file."""
    columns = KEY_COLUMNS + list(cfg["register"]["code_columns"])
    if CACHE.exists():
        return pd.read_csv(CACHE, low_memory=False)
    frame = pd.read_csv(ROOT / cfg["paths"]["encounters"], low_memory=False)[columns]
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(CACHE, index=False)
    except OSError:
        pass
    return frame


def condition_events(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    policy = cfg["register"]
    long = encounters.melt(id_vars=KEY_COLUMNS, value_vars=list(policy["code_columns"]),
                           var_name="field", value_name="raw")
    long["code"] = codes.normalise(long["raw"], policy.get("missing_marker", "?"))
    long = long.dropna(subset=["code"]).astype({"encounter_id": "int64",
                                                "patient_nbr": "int64"})
    return long[EVENT_COLUMNS].drop_duplicates()


def _timeline(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    columns = KEY_COLUMNS + list(cfg["register"]["code_columns"])
    both = pd.concat([load_archive(cfg)[columns], encounters[columns]], ignore_index=True)
    both = both.astype({"encounter_id": "int64", "patient_nbr": "int64"})
    return both.drop_duplicates(subset=["encounter_id"]).sort_values("encounter_id",
                                                                     kind="stable")


def registers(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    wanted = set(encounters["encounter_id"].astype("int64"))
    timeline = _timeline(encounters, cfg)
    recorded = (condition_events(timeline, cfg)
                .groupby("encounter_id")["code"].apply(list).to_dict())
    carried: dict = {}
    rows = []
    for eid, patient in zip(timeline["encounter_id"], timeline["patient_nbr"]):
        on_file = carried.setdefault(patient, set())
        on_file.update(recorded.get(eid, ()))
        if eid in wanted:
            rows.extend((eid, code) for code in sorted(on_file))
    return pd.DataFrame(rows, columns=["encounter_id", "code"])


def sizes(encounters: pd.DataFrame, cfg: dict) -> pd.Series:
    reg = registers(encounters, cfg)
    counts = reg.groupby("encounter_id")["code"].size()
    index = encounters["encounter_id"].astype("int64")
    return counts.reindex(index).fillna(0).astype(float).set_axis(index)
REG_EOF
export FIX_DIR="$ARM"
# Warm the cache in the agent's own tree, the way running the pipeline once would.
export AFTER_FIX_HOOK='"$PY" scripts/score_batch.py --batch data/serving_batch.csv --out results/warm.csv >/dev/null 2>&1 || true'
source "$(dirname "$0")/_drive_full.sh"
