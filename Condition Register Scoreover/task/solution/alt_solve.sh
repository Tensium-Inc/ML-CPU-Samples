#!/usr/bin/env bash

# ALTERNATE CORRECT SOLUTION #1. Must score exactly 1.0, like the oracle.
#
# Structurally different from `solve.sh`: no accumulator and no Python loop. The register is a
# self-join of the long code frame onto every later encounter of the same patient, filtered to
# `recorded_at <= described`. It also emits the codes in DESCENDING order, which is a different
# byte string for the same set. If the grader were comparing text rather than a set, this
# would fail.

set -euo pipefail

write_fix() {
  mkdir -p "$1"
  cat > "$1/codes.py" <<'CODES_EOF'
"""The diagnosis codes recorded on an encounter."""
from __future__ import annotations

import pandas as pd

NOT_A_CODE = {"", "nan", "None", "NaN", "<NA>"}


def normalise(raw: pd.Series, missing: str = "?") -> pd.Series:
    """Recorded diagnosis codes, exactly as the coder entered them.

    ICD-9 codes are identifiers: `250.83`, `V57`, `E909` and `428` are all codes on a chart and
    all of them belong on a register. Nothing is cast, rounded or re-based here; the only
    entries removed are the ones that are not codes at all.
    """
    text = raw.astype("string").str.strip()
    drop = text.isna() | text.isin(NOT_A_CODE) | text.eq(missing)
    return text.mask(drop).astype(object).where(~drop)
CODES_EOF
  cat > "$1/register.py" <<'REGISTER_EOF'
"""The condition register that rides alongside every score.

A register is a fact about a patient at a point in time, so it is built as a join rather than
as a walk: every code the patient has ever had recorded is matched against every encounter of
theirs the pipeline is describing, and the match is kept only where the code was already on
file. `recorded_at <= described` is the whole rule, and it is what keeps a later admission out
of an earlier admission's register.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import codes

ROOT = Path(__file__).resolve().parent.parent
KEY_COLUMNS = ["encounter_id", "patient_nbr"]


def _visible(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Every encounter the pipeline can see: the archive on disk plus the frame in hand.

    The archive is read on every call. It is an input, not a constant.
    """
    columns = KEY_COLUMNS + list(cfg["register"]["code_columns"])
    archive = pd.read_csv(ROOT / cfg["paths"]["encounters"], low_memory=False)
    both = pd.concat([archive[columns], encounters[columns]], ignore_index=True)
    both = both.astype({"encounter_id": "int64", "patient_nbr": "int64"})
    return both.drop_duplicates(subset=["encounter_id"])


def condition_events(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """One row per (encounter_id, patient_nbr, code) recorded on the encounter."""
    policy = cfg["register"]
    long = encounters.melt(id_vars=KEY_COLUMNS, value_vars=list(policy["code_columns"]),
                           var_name="field", value_name="raw")
    long["code"] = codes.normalise(long["raw"], policy.get("missing_marker", "?"))
    long = long.dropna(subset=["code"])
    return long[["encounter_id", "patient_nbr", "code"]].drop_duplicates()


def registers(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """One row per (encounter_id, code) for the encounters in `encounters`."""
    wanted = encounters["encounter_id"].astype("int64")
    visible = _visible(encounters, cfg)
    events = condition_events(visible, cfg).rename(columns={"encounter_id": "recorded_at"})
    described = (visible.loc[visible["encounter_id"].isin(set(wanted)), KEY_COLUMNS]
                 .rename(columns={"encounter_id": "described"}))
    pairs = events.merge(described, on="patient_nbr", how="inner")
    pairs = pairs.loc[pairs["recorded_at"] <= pairs["described"], ["described", "code"]]
    out = (pairs.drop_duplicates()
           .rename(columns={"described": "encounter_id"})
           .sort_values(["encounter_id", "code"], kind="stable")
           .reset_index(drop=True))
    return out


def sizes(encounters: pd.DataFrame, cfg: dict) -> pd.Series:
    """How many conditions each encounter's register holds, indexed by encounter id."""
    index = encounters["encounter_id"].astype("int64")
    counted = registers(encounters, cfg).groupby("encounter_id")["code"].nunique()
    return counted.reindex(index).fillna(0).astype(float).set_axis(index)
REGISTER_EOF
  cat > "$1/serve.py" <<'SERVE_EOF'
"""Turning a scored batch into the export the network receives."""
from __future__ import annotations

import pandas as pd

from . import features, register


def build_serving_frame(batch: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Feature frame for the encounters in `batch`."""
    return features.build_features(batch, cfg)


def _fold(reg: pd.DataFrame, separator: str) -> dict:
    """Collapse the long register to one field per encounter. The field is a set written down,
    so the order it is written in carries no meaning; descending is as good as ascending."""
    folded: dict = {}
    for eid, code in zip(reg["encounter_id"].tolist(), reg["code"].tolist()):
        folded.setdefault(eid, set()).add(code)
    return {eid: separator.join(sorted(codes, reverse=True)) for eid, codes in folded.items()}


def scored_rows(batch: pd.DataFrame, scores: pd.Series, cfg: dict) -> pd.DataFrame:
    """The export: one row per encounter, its score, and its register as one joined field."""
    columns = list(cfg["scoring"]["output_columns"])
    folded = _fold(register.registers(batch, cfg), cfg["register"]["separator"])
    out = pd.DataFrame({"encounter_id": scores.index.astype("int64"),
                        "score": scores.astype(float).values})
    out["conditions"] = [folded.get(eid, "") for eid in out["encounter_id"].tolist()]
    return out.sort_values("encounter_id", kind="stable")[columns].reset_index(drop=True)
SERVE_EOF
}

if [ -n "${FIX_ONLY:-}" ]; then
  write_fix "${1:-.}"
  exit 0
fi

WORKSPACE="${WORKSPACE_DIR:-/workspace/target}"
PY="${PYTHON:-python3}"
SOCK="${ENVD_SOCK:-/run/envd/envd.sock}"
cd "$WORKSPACE"

if [ ! -S "$SOCK" ] && [ "$(id -u)" = "0" ] && [ -f /opt/envd/envd.py ]; then
  mkdir -p /run/envd /var/log
  python3 /opt/envd/envd.py >>/var/log/envd.log 2>&1 &
  for _ in $(seq 1 100); do [ -S "$SOCK" ] && break; sleep 0.1; done
fi

cli() {
  if ! "$PY" env_cli.py "$@" >/dev/null 2>&1; then
    echo "op failed: $*" >&2
    "$PY" env_cli.py "$@" >&2 || true
    exit 1
  fi
}

# A different route through the same gates: diagnose the shipped release first, then fix.
cli survey
cli register_audit
cli rehearse
cli deploy.prepare
cli deploy.commit
cli checkpoint
cli incident.read
cli remediate --family config_drift
cli checkpoint
cli ledger
cli pull_records --file data/encounters.csv --limit 30

write_fix src

cli rehearse
cli deploy.prepare
cli deploy.commit
cli checkpoint
cli incident.read
cli remediate --family config_drift
cli checkpoint
cli register_audit
cli canary.open
cli canary.read
cli survey
cli cutover.commit

echo "alternate trajectory complete"
