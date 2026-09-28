#!/usr/bin/env bash
# Half the deciding fix: the register accumulates across a patient's admissions, but the codes
# still go through the delivered code table, so the subdivided series is folded onto its root
# before it reaches a register. Must score 0. This is what proves the code table is
# load-bearing on its own, independently of the accumulation.
set -euo pipefail
. "$(dirname "$0")/_arm.sh"

arm_python <<'PATCH'
import sys
from pathlib import Path

arm = Path(sys.argv[1])
path = arm / "register.py"
text = path.read_text(encoding="utf-8")

old = '    long["code"] = codes.normalise(long["raw"], policy.get("missing_marker", "?"))'
new = ('    charted = codes.normalise(long["raw"], policy.get("missing_marker", "?"))\n'
       '    _table = pd.read_csv(ROOT / policy["code_table"], dtype=str)\n'
       '    _table = _table.set_index("charted_code")["register_code"]\n'
       '    long["code"] = charted.map(_table).fillna(charted)')
assert old in text, "register.py anchor not found in the gold arm"
path.write_text(text.replace(old, new), encoding="utf-8")
PATCH

export FIX_DIR="$ARM"
source "$(dirname "$0")/_drive_full.sh"
