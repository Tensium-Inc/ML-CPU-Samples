#!/usr/bin/env bash
# NEGATIVE -- every rule correct, the whole build inlined into the entry point and
# src/ deleted. The multi-file floor, measured on a trajectory that SOLVES the
# problem: the table it writes is exact. It must still score zero.
#
# It floors at check.release, which asks the build for src.schema.contract() and
# src.requests.audit(rows). A build with no modules cannot answer either.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes
rm -rf "$WS/src"
cat > "$WS/harness.py" <<'PY'
#!/usr/bin/env python3
"""Funding-request table -- one file, no modules. Correct rules throughout."""
from __future__ import annotations

import argparse
import csv
import gzip
from pathlib import Path

COLUMNS = ["funding_request_number", "label", "applicant_key",
           "committed_cents", "filed_months",
           "filed_commitment_cents", "filed_pre_discount_cents", "filed_discount_pct"]
DECIDED = {"QK7", "VR9", "ZP2", "VD4"}
FUNDED = {"QK7", "VR9"}


def cents(raw):
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return str(int(round(float(text) * 100)))
    except ValueError:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    opts = ap.parse_args()
    path = Path(opts.data_root) / "erate_frn_status_fy2024.csv.gz"
    filed, adj = {}, {}
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            frn = (row.get("funding_request_number") or "").strip()
            if not frn:
                continue
            if row["form_version"] == "Original":
                filed.setdefault(frn, row)
            elif row["form_version"] == "Current":
                adj.setdefault(frn, row)
    with open(opts.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for frn in sorted(set(filed) | set(adj)):
            f, a = filed.get(frn), adj.get(frn)
            status = (a or {}).get("form_471_frn_status_name")
            if status not in DECIDED:
                label = "undecided"
            elif status not in FUNDED:
                label = "not_funded"
            else:
                try:
                    money = float((a.get("funding_commitment_request") or "").strip())
                except ValueError:
                    money = None
                wave = bool((a.get("wave_sequence_number") or "").strip())
                label = "funded" if (money not in (None, 0.0) and wave) else "not_funded"
            writer.writerow([
                frn, label, (f or a)["ben"],
                cents(a["funding_commitment_request"]) if a else "",
                (f["months_of_service"].strip() if f else ""),
                cents(f["funding_commitment_request"]) if f else "",
                cents(f["total_pre_discount_costs"]) if f else "",
                (f["dis_pct"].strip() if f else ""),
            ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate
op check.release || true    # refused: there are no modules to ask
exit 0
