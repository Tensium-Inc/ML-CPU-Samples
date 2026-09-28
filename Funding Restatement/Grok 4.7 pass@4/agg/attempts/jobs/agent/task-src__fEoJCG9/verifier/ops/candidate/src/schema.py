"""What the deliverable looks like, and how it is written.

One place, so callers agree with the writer. `check.release` asks this build what
shape it writes and checks the answer against what the desk signed off; declaring
one thing and writing another is the failure this exists to catch, so
`harness.py` takes its header from `contract()` rather than from a second copy.
"""

from __future__ import annotations

import csv

COLUMNS = ["funding_request_number", "label", "applicant_key",
           "committed_cents", "filed_months",
           "filed_commitment_cents", "filed_pre_discount_cents", "filed_discount_pct"]


def contract() -> dict:
    """The shape of the file this build writes."""
    return {"columns": list(COLUMNS), "rows_per_request": 1}


def write(table: dict[str, dict], out_path) -> None:
    columns = contract()["columns"]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for frn in sorted(table):
            row = table[frn]
            writer.writerow([frn, *(row[c] for c in columns[1:])])
