#!/usr/bin/env python3
"""Build the funding-request table for the scoring desk.

    python3 harness.py --data-root <DIR> --out <FILE>

Writes csv with one row per distinct funding request.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import keys, labels, loading, requests, schema


def _text(row: dict | None, column: str) -> str:
    if row is None:
        return ""
    return row.get(column, "") or ""


def build(data_root) -> dict[str, dict]:
    """The table, keyed by funding request number.

    Filed figures are what the applicant asked for, read off the Original
    version. The commitment as granted is read off the Current version. They
    are the same money column of the extract and they are not the same number.
    A request that has only one version reports the side it does not have as
    empty rather than borrowing the other side's number.
    """
    rows = loading.read_rows(data_root)
    grouped = requests.versions_of(rows)
    table: dict[str, dict] = {}
    for frn, versions in grouped.items():
        filed = versions.get("Original")
        adjudicated = versions.get("Current")
        identity = adjudicated or filed
        table[frn] = {
            "label": labels.label_for(versions),
            "applicant_key": keys.applicant_key(identity),
            "committed_cents": requests.cents(_text(adjudicated, "funding_commitment_request")),
            "filed_months": _text(filed, "months_of_service"),
            "filed_commitment_cents": requests.cents(_text(filed, "funding_commitment_request")),
            "filed_pre_discount_cents": requests.cents(_text(filed, "total_pre_discount_costs")),
            "filed_discount_pct": _text(filed, "dis_pct"),
        }
    return table


def main() -> int:
    ap = argparse.ArgumentParser(description="build the funding-request table")
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    opts = ap.parse_args()
    table = build(opts.data_root)
    schema.write(table, Path(opts.out))
    print(f"built {len(table):,} requests -> {opts.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
