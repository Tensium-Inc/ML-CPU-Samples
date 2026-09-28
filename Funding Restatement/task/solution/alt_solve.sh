#!/usr/bin/env bash
# ALTERNATE 1 -- a second correct build. Must also score exactly 1.0.
#
# Different machinery from gold on purpose. Gold walks the rows once and keeps
# two dictionaries; this one loads the extract with pandas and PIVOTS on
# form_version, so the two versions of a request become two columns of one frame
# and the join is a reindex rather than a lookup. The loader differs too.
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
"""Requests as a pivot over form_version.

The extract is long-format: one row per (request, version). Pivoting turns it
into one row per request with the two versions side by side, which is what makes
"take this field from that version" a column selection rather than a lookup.
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
    import pandas as pd

    frame = pd.DataFrame(rows)
    frame = frame[frame["funding_request_number"] != ""]
    out = {}
    for version, key in ((AS_FILED, "filed"), (AS_ADJUDICATED, "adjudicated")):
        part = frame[frame["form_version"] == version].drop_duplicates(
            subset="funding_request_number", keep="first")
        for record in part.to_dict("records"):
            out.setdefault(record["funding_request_number"],
                           {"filed": None, "adjudicated": None})[key] = record
    return out


def audit(rows):
    seen = {}
    for row in rows:
        frn = row["funding_request_number"]
        if frn:
            seen.setdefault(frn, set()).add(row["form_version"])
    return {"rows": len(rows), "requests": len(seen),
            "carrying_both_versions": sum(1 for v in seen.values() if len(v) > 1)}
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
