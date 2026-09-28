#!/usr/bin/env bash
# ALTERNATE 2 -- a third correct build. Must also score exactly 1.0.
#
# Different machinery again. Gold keeps two dictionaries and alternate 1 pivots a
# frame; this one sorts the rows by (request, version) and walks them once with
# itertools.groupby, emitting each request as its group closes. No index and no
# frame -- a single ordered pass.
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

emit() {
  local dest="$1"; mkdir -p "$dest/src"
  cat > "$dest/src/requests.py" <<'PY'
"""Requests by one ordered pass with itertools.groupby.

Sort by (request, version) and every row of a request arrives consecutively, so
the group can be closed and emitted without holding an index of the whole
extract. `Current` sorts before `Original`, which is why the version is matched
by name rather than by position.
"""
from __future__ import annotations

from itertools import groupby
from operator import itemgetter

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
    usable = [r for r in rows if r["funding_request_number"]]
    usable.sort(key=itemgetter("funding_request_number", "form_version"))
    out = {}
    for frn, group in groupby(usable, key=itemgetter("funding_request_number")):
        pair = {"filed": None, "adjudicated": None}
        for row in group:
            if row["form_version"] == AS_FILED and pair["filed"] is None:
                pair["filed"] = row
            elif row["form_version"] == AS_ADJUDICATED and pair["adjudicated"] is None:
                pair["adjudicated"] = row
        out[frn] = pair
    return out


def audit(rows):
    usable = sorted((r for r in rows if r["funding_request_number"]),
                    key=itemgetter("funding_request_number"))
    requests = both = 0
    for _frn, group in groupby(usable, key=itemgetter("funding_request_number")):
        requests += 1
        if len({r["form_version"] for r in group}) > 1:
            both += 1
    return {"rows": len(rows), "requests": requests, "carrying_both_versions": both}
PY
  cat > "$dest/src/labels.py" <<'PY'
"""The outcome, read off the adjudicated version.

A cancelled request is decided and not funded: the extract stamps
`pending_reason = FCDL Issued` on it exactly as on a denial, and its adjudicated
commitment is zero.
"""
from __future__ import annotations

NOT_DECIDED_IF_ABSENT = None
DECIDED = ("QK7", "VR9", "ZP2", "VD4")
FUNDED = ("QK7", "VR9")

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
    status = (adjudicated or {}).get("form_471_frn_status_name")
    if status not in DECIDED:
        return "undecided"
    if status not in FUNDED:
        return "not_funded"
    return "funded" if _really_funded(adjudicated) else "not_funded"
PY
  cat > "$dest/src/keys.py" <<'PY'
"""The applicant key. The billed entity number identifies the filer; the name
does not, and 600 names in this extract are shared by more than one entity."""
from __future__ import annotations


def applicant_key(row):
    return row["ben"]
PY
  cat > "$dest/harness.py" <<'PY'
#!/usr/bin/env python3
"""Funding-request table -- entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import keys, labels, loading, requests, schema


def build(data_root):
    pairs = requests.collect(loading.read_rows(data_root))
    out = {}
    for frn, pair in pairs.items():
        filed = pair["filed"]
        out[frn] = {
            "label": labels.label(pair["adjudicated"]),
            "applicant_key": keys.applicant_key(filed or pair["adjudicated"]),
            "filed_commitment_cents":
                requests.cents(filed["funding_commitment_request"]) if filed else "",
            "filed_pre_discount_cents":
                requests.cents(filed["total_pre_discount_costs"]) if filed else "",
            "filed_discount_pct": (filed["dis_pct"] if filed else ""),
            # Read off the ADJUDICATED row, not the filed one. It is the same
            # money column and a different number on 13,585 requests.
            "committed_cents":
                requests.cents(pair["adjudicated"]["funding_commitment_request"])
                if pair["adjudicated"] else "",
            "filed_months": (filed["months_of_service"] if filed else ""),
        }
    return out


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
}

say "notes"; read_all_notes
say "shape"; obs profile >/dev/null; obs sample_rows >/dev/null
say "rebuild"; emit "$WS"
python3 "$WS/harness.py" --data-root "$WS/data" --out /tmp/alt_requests.csv
say "drive"; drive
say "done"
