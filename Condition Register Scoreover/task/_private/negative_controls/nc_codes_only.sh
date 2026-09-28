#!/usr/bin/env bash
# The other half of the deciding fix: codes reach the register exactly as charted, the archive is
# re-read, the export is shaped right, and the register still holds only what the admission in
# hand charts. Must score 0. This is what proves the carry-forward is load-bearing on its own,
# independently of the code table.
set -euo pipefail
. "$(dirname "$0")/_arm.sh"

arm_python <<'PATCH'
import sys
from pathlib import Path

arm = Path(sys.argv[1])
path = arm / "register.py"
text = path.read_text(encoding="utf-8")

old = """    carried: dict[int, set] = {}
    rows: list[tuple[int, str]] = []
    for eid, patient in zip(timeline["encounter_id"], timeline["patient_nbr"]):
        on_file = carried.setdefault(patient, set())
        on_file.update(recorded.get(eid, ()))
        if eid in wanted:
            rows.extend((eid, code) for code in sorted(on_file))
"""
new = """    rows: list[tuple[int, str]] = []
    for eid in timeline["encounter_id"]:
        if eid in wanted:
            rows.extend((eid, code) for code in sorted(set(recorded.get(eid, ()))))
"""
assert old in text, "register.py accumulator anchor not found in the gold arm"
path.write_text(text.replace(old, new), encoding="utf-8")
PATCH

export FIX_DIR="$ARM"
source "$(dirname "$0")/_drive_full.sh"
