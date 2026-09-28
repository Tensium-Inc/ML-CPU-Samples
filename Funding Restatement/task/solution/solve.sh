#!/usr/bin/env bash
# GOLD -- the positive control. Must score exactly 1.0.
#
# Two halves and both are required: rebuild the table to the ops notes, and drive
# the incident through the service. Either alone scores zero.
#
# The rules here are all SPECIFIED -- this task withholds no rule and rations no
# oracle. What it withholds is nothing at all: the difficulty is that the extract
# records form versions rather than requests, and the desk's own check reports a
# better number the more wrong the table is.
set -euo pipefail
WS="${WORKSPACE_DIR:-/workspace/target}"
CLI="python3 $WS/env_cli.py"
RECEIPT=""
say() { printf '\n>>> %s\n' "$*"; }
# env_cli emits ONE json object and nothing else, so a plain json.load is safe.
op() {
  local out
  out="$($CLI "$@" ${RECEIPT:+--receipt "$RECEIPT"})"
  printf '%s\n' "$out"
  RECEIPT="$(printf '%s' "$out" | python3 -c 'import json,sys
print(json.load(sys.stdin).get("receipt") or "")')"
  printf '%s' "$out" | python3 -c 'import json,sys
sys.exit(0 if json.load(sys.stdin).get("ok") else 1)'
}
obs() { $CLI "$@"; }
read_all_notes() {
  for topic in $(obs policy.list | python3 -c 'import json,sys
print(" ".join(json.load(sys.stdin)["topics"]))'); do
    obs policy.read --topic "$topic" >/dev/null; echo "  read $topic"
  done
}
drive() {
  op reproduce; op deploy; op validate; op diagnostics.read
  op recovery.apply --family stale_applicant_cache
  op validate; op check.release; op submit
}

write_package() {
  local dest="$1"; mkdir -p "$dest/src"
  cat > "$dest/harness.py" <<'PY'
#!/usr/bin/env python3
"""Funding-request table -- entry point.

Rebuilt to the ops notes. Nothing is decided here: the command line, the order
the passes run in and where the rows go is all this file does.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import keys, labels, loading, requests, schema


def build(data_root):
    rows = loading.read_rows(data_root)
    table = {}
    for frn, pair in requests.collect(rows).items():
        filed, adjudicated = pair["filed"], pair["adjudicated"]
        table[frn] = {
            "label": labels.label(adjudicated),
            "applicant_key": keys.applicant_key(filed or adjudicated),
            "filed_commitment_cents":
                requests.cents(filed["funding_commitment_request"]) if filed else "",
            "filed_pre_discount_cents":
                requests.cents(filed["total_pre_discount_costs"]) if filed else "",
            "filed_discount_pct": (filed["dis_pct"] if filed else ""),
            # Read off the ADJUDICATED row, not the filed one. It is the same
            # money column and a different number on 13,585 requests.
            "committed_cents":
                requests.cents(adjudicated["funding_commitment_request"]) if adjudicated else "",
            "filed_months": (filed["months_of_service"] if filed else ""),
        }
    return table


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    table = build(a.data_root)
    schema.write(table, Path(a.out))
    print(f"built {len(table):,} requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
  cat > "$dest/src/requests.py" <<'PY'
"""Group form-version rows into requests, and keep both versions of each.

The extract records FORM VERSIONS. A request appears once per version, so the
grouping has to keep both and let the caller say which one each field comes from
-- collapsing to one row here would make that choice invisible.
"""
from __future__ import annotations

AS_FILED = "Original"
AS_ADJUDICATED = "Current"


def cents(raw):
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return str(int(round(float(text) * 100)))
    except ValueError:
        return ""


def collect(rows):
    filed, adjudicated = {}, {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        if row["form_version"] == AS_FILED:
            filed.setdefault(frn, row)
        elif row["form_version"] == AS_ADJUDICATED:
            adjudicated.setdefault(frn, row)
    return {frn: {"filed": filed.get(frn), "adjudicated": adjudicated.get(frn)}
            for frn in set(filed) | set(adjudicated)}


def audit(rows):
    """This build's own account of the extract, over the rows handed in."""
    seen = {}
    for row in rows:
        frn = row["funding_request_number"]
        if frn:
            seen.setdefault(frn, set()).add(row["form_version"])
    return {"rows": len(rows), "requests": len(collect(rows)),
            "carrying_both_versions": sum(1 for v in seen.values() if len(v) > 1)}
PY
  cat > "$dest/src/labels.py" <<'PY'
"""The outcome of a request, read off the adjudicated version.

A cancelled request IS decided: the extract stamps `pending_reason = FCDL Issued`
on it exactly as it does on a funded or denied one, which is the decision letter
going out, and its adjudicated commitment is 0.00 like every denial. It is an
adverse outcome, not a withdrawal before review.
"""
from __future__ import annotations

DECIDED = {"QK7", "VR9", "ZP2", "VD4"}
FUNDED = {"QK7", "VR9"}

def _committed(row):
    try:
        return float((row.get("funding_commitment_request") or "").strip())
    except ValueError:
        return None


def _carried(row):
    return bool((row.get("wave_sequence_number") or "").strip())


def _really_funded(row):
    """Approved on paper is not funded. The fund has to have committed money
    and a wave has to have carried it -- the oracle splits 631 requests that
    say Funded and were not."""
    return _committed(row) not in (None, 0.0) and _carried(row)




def label(adjudicated):
    if adjudicated is None or adjudicated.get("form_471_frn_status_name") not in DECIDED:
        return "undecided"
    if adjudicated["form_471_frn_status_name"] not in FUNDED:
        return "not_funded"
    return "funded" if _really_funded(adjudicated) else "not_funded"
PY
  cat > "$dest/src/keys.py" <<'PY'
"""The applicant key: the billed entity number, never the name."""
from __future__ import annotations


def applicant_key(row):
    return row["ben"]
PY
}

say "read every ops note"; read_all_notes
say "look at the shape of the extract"; obs profile >/dev/null; obs sample_rows >/dev/null
say "rebuild the package"; write_package "$WS"
python3 "$WS/harness.py" --data-root "$WS/data" --out /tmp/gold_requests.csv
say "drive the incident"; drive
say "done"
