#!/usr/bin/env bash

# ALTERNATE CORRECT SOLUTION #2. Must score exactly 1.0, like the oracle.
#
# Structurally different again: the register never exists in long form. Each patient's history
# is walked once with an expanding set and the joined field is built directly, so `registers()`
# is derived FROM the export column rather than the other way round. Codes are separated by a
# regex rather than a melt, and the field is written in first-seen order.

set -euo pipefail

write_fix() {
  mkdir -p "$1"
  cat > "$1/codes.py" <<'CODES_EOF'
"""The diagnosis codes recorded on an encounter."""
from __future__ import annotations

import re

import pandas as pd

# A code is a numeric or supplementary ICD-9 identifier, optionally with a decimal part.
CODE = re.compile(r"^[VE]?\d+(\.\d+)?$", re.IGNORECASE)


def is_code(value: object, missing: str = "?") -> bool:
    text = str(value).strip()
    return bool(text) and text != missing and bool(CODE.match(text))


def normalise(raw: pd.Series, missing: str = "?") -> pd.Series:
    """Recorded diagnosis codes, kept verbatim.

    Nothing is coerced to a number: the V and E series are codes too, and the decimal part of a
    code is part of its identity rather than a magnitude.
    """
    text = raw.astype(str).str.strip()
    keep = text.map(lambda value: is_code(value, missing))
    return text.where(keep)
CODES_EOF
  cat > "$1/register.py" <<'REGISTER_EOF'
"""The condition register that rides alongside every score.

Built patient by patient. A patient's conditions are cumulative, since a code recorded once
stays on their record, so walking their encounters in order and carrying the set forward gives
register as it stood at each admission. Encounters that have not happened yet are simply not
reached by the walk, which is what keeps them out.

The history walked is the archive on disk plus whatever frame is being described, because those
two together are everything the pipeline has ever been told about the patient.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import codes

ROOT = Path(__file__).resolve().parent.parent


def _history(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    columns = ["encounter_id", "patient_nbr"] + list(cfg["register"]["code_columns"])
    archive = pd.read_csv(ROOT / cfg["paths"]["encounters"], low_memory=False)
    frame = pd.concat([archive[columns], encounters[columns]], ignore_index=True)
    frame = frame.astype({"encounter_id": "int64", "patient_nbr": "int64"})
    return frame.drop_duplicates(subset=["encounter_id"]).sort_values("encounter_id",
                                                                     kind="stable")


def joined_registers(encounters: pd.DataFrame, cfg: dict) -> pd.Series:
    """The register for every encounter in `encounters`, already joined into one field."""
    policy = cfg["register"]
    separator = policy["separator"]
    missing = policy.get("missing_marker", "?")
    fields = list(policy["code_columns"])
    wanted = set(encounters["encounter_id"].astype("int64"))

    history = _history(encounters, cfg)
    out: dict[int, str] = {}
    for _, group in history.groupby("patient_nbr", sort=False):
        on_file: list[str] = []
        held: set[str] = set()
        for record in group.to_dict("records"):
            for field in fields:
                value = str(record[field]).strip()
                if codes.is_code(value, missing) and value not in held:
                    held.add(value)
                    on_file.append(value)
            eid = int(record["encounter_id"])
            if eid in wanted:
                out[eid] = separator.join(on_file)
    index = encounters["encounter_id"].astype("int64")
    return pd.Series([out.get(eid, "") for eid in index], index=index, name="conditions")


def registers(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """The same registers in long form, for anything that wants a row per code."""
    separator = cfg["register"]["separator"]
    rows = []
    for eid, field in joined_registers(encounters, cfg).items():
        rows.extend((int(eid), code) for code in field.split(separator) if code)
    return pd.DataFrame(rows, columns=["encounter_id", "code"])


def sizes(encounters: pd.DataFrame, cfg: dict) -> pd.Series:
    """How many conditions each encounter's register holds, indexed by encounter id."""
    separator = cfg["register"]["separator"]
    joined = joined_registers(encounters, cfg)
    return joined.map(lambda field: float(len([c for c in field.split(separator) if c])))
REGISTER_EOF
  cat > "$1/serve.py" <<'SERVE_EOF'
"""Turning a scored batch into the export the network receives."""
from __future__ import annotations

import pandas as pd

from . import features, register


def build_serving_frame(batch: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Feature frame for the encounters in `batch`."""
    return features.build_features(batch, cfg)


def scored_rows(batch: pd.DataFrame, scores: pd.Series, cfg: dict) -> pd.DataFrame:
    """The export: one row per encounter, its score, and its register as one joined field."""
    columns = list(cfg["scoring"]["output_columns"])
    joined = register.joined_registers(batch, cfg)
    out = pd.DataFrame({"encounter_id": scores.index.astype("int64"),
                        "score": scores.astype(float).values})
    out["conditions"] = out["encounter_id"].map(joined).fillna("")
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

# This route reads the record before touching the release path at all.
cli survey
cli ledger
cli pull_records
cli pull_records --file data/encounters.csv
cli register_audit

write_fix src

cli rehearse
cli deploy.prepare
cli deploy.commit
cli checkpoint
cli incident.read
cli remediate --family config_drift
cli checkpoint
cli register_audit
cli ledger
cli canary.open
cli canary.read
cli cutover.commit

echo "second alternate trajectory complete"
