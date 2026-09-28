#!/usr/bin/env bash

# ORACLE / positive control. Must score exactly 1.0.
#
# Self-contained on purpose: a runner that copies only the three .sh files still gets a working
# solution. `FIX_ONLY=1 bash solution/solve.sh <dir>` writes the fix and exits, which is how the
# controls and the perturbation check reuse it without duplicating a second copy of gold.

set -euo pipefail

write_fix() {
  mkdir -p "$1"
  cat > "$1/codes.py" <<'CODES_EOF'
"""The diagnosis codes recorded on an encounter."""
from __future__ import annotations

import pandas as pd

BLANKS = ("", "nan", "None")


def normalise(raw: pd.Series, missing: str = "?") -> pd.Series:
    """Recorded diagnosis codes, tidied for use as register entries.

    A diagnosis code is an identifier, not a quantity. The corpus uses the numeric series, the
    supplementary V and E series and decimal subdivisions, and all three are codes a patient is
    carrying; keeping only the ones that happen to parse as a number silently drops conditions
    off the register. The missing marker and blank cells come back as NaN.
    """
    text = raw.astype(str).str.strip()
    return text.where(~text.isin((missing, *BLANKS)))
CODES_EOF
  cat > "$1/register.py" <<'REGISTER_EOF'
"""The condition register that rides alongside every score.

The register for an encounter is the set of distinct diagnosis codes on file for that patient
as of that admission. Conditions are a property of the patient, not of one admission: a code
recorded at an earlier encounter is still on file at a later one, so the register accumulates
per patient in encounter order. It accumulates over everything the pipeline can see, the
encounter archive and the batch being scored, and it stops at the encounter being described,
because a register is what was known then, not what is known now.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import codes

ROOT = Path(__file__).resolve().parent.parent
EVENT_COLUMNS = ["encounter_id", "patient_nbr", "code"]
KEY_COLUMNS = ["encounter_id", "patient_nbr"]


def load_archive(cfg: dict) -> pd.DataFrame:
    """The encounter history on disk. Read every time, never cached: it can change."""
    return pd.read_csv(ROOT / cfg["paths"]["encounters"], low_memory=False)


def condition_events(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """One row per (encounter_id, patient_nbr, code) recorded on the encounter."""
    policy = cfg["register"]
    long = encounters.melt(id_vars=KEY_COLUMNS, value_vars=list(policy["code_columns"]),
                           var_name="field", value_name="raw")
    long["code"] = codes.normalise(long["raw"], policy.get("missing_marker", "?"))
    long = long.dropna(subset=["code"]).astype({"encounter_id": "int64",
                                                "patient_nbr": "int64"})
    return long[EVENT_COLUMNS].drop_duplicates()


def _timeline(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Every encounter the pipeline can see, in the order they happened."""
    both = pd.concat([load_archive(cfg)[KEY_COLUMNS + list(cfg["register"]["code_columns"])],
                      encounters[KEY_COLUMNS + list(cfg["register"]["code_columns"])]],
                     ignore_index=True)
    both["encounter_id"] = both["encounter_id"].astype("int64")
    both["patient_nbr"] = both["patient_nbr"].astype("int64")
    return (both.drop_duplicates(subset=["encounter_id"])
            .sort_values("encounter_id", kind="stable"))


def registers(encounters: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """The condition register for every encounter in `encounters`, in long form.

    One row per (encounter_id, code), distinct codes only, in a stable order.
    """
    wanted = set(encounters["encounter_id"].astype("int64"))
    timeline = _timeline(encounters, cfg)
    recorded = (condition_events(timeline, cfg)
                .groupby("encounter_id")["code"].apply(list).to_dict())
    carried: dict[int, set] = {}
    rows: list[tuple[int, str]] = []
    for eid, patient in zip(timeline["encounter_id"], timeline["patient_nbr"]):
        on_file = carried.setdefault(patient, set())
        on_file.update(recorded.get(eid, ()))
        if eid in wanted:
            rows.extend((eid, code) for code in sorted(on_file))
    return pd.DataFrame(rows, columns=["encounter_id", "code"])


def sizes(encounters: pd.DataFrame, cfg: dict) -> pd.Series:
    """How many conditions each encounter's register holds, indexed by encounter id."""
    reg = registers(encounters, cfg)
    counts = reg.groupby("encounter_id")["code"].size()
    index = encounters["encounter_id"].astype("int64")
    return counts.reindex(index).fillna(0).astype(float).set_axis(index)
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
    separator = cfg["register"]["separator"]
    reg = register.registers(batch, cfg)
    joined = reg.groupby("encounter_id")["code"].agg(lambda s: separator.join(sorted(set(s))))
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

# The image entrypoint starts the release service at boot. If a harness reached this script
# without that having happened and we are root, start it here rather than failing for a reason
# that has nothing to do with the solution.
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

cli survey
cli ledger
cli pull_records
cli register_audit

# Take the release path as it stands and see what the builder actually ships.
cli rehearse
cli deploy.prepare
cli deploy.commit
cli checkpoint
cli incident.read
cli remediate --family config_drift
cli checkpoint

# The same patient across the archive and the batch, before changing anything.
cli pull_records --file data/encounters.csv
cli register_audit --file data/encounters.csv

write_fix src

cli rehearse
cli deploy.prepare
cli deploy.commit
cli checkpoint
cli incident.read
cli remediate --family config_drift
cli checkpoint

cli ledger
cli canary.open
cli canary.read
cli cutover.commit

echo "gold trajectory complete"
