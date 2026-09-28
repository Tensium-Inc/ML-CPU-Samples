#!/usr/bin/env python3
"""Build the funding-request table for the scoring desk.

    python3 harness.py --data-root <DIR> --out <FILE>

Writes csv with one row per distinct funding request.

Deliberately thin. It reads the extract, asks each module its own question and
writes the answers down. The questions live in `src/` because that is where they
can be found, argued with and changed.

Every field is read off the version of the request it is defined on:

    committed_cents            the adjudicated version -- what the fund granted
    filed_*                    the filed version -- what the applicant asked for

The two versions do not carry the same numbers (adjudication restates them), so
a field whose version is missing from the extract is reported as the empty
string: nothing to report is a different fact from zero.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import keys, labels, loading, requests, schema


def build(data_root) -> dict[str, dict]:
    """The table, keyed by funding request number."""
    rows = loading.read_rows(data_root)
    table: dict[str, dict] = {}
    for frn, entry in requests.collect(rows).items():
        filed = entry["filed"]
        adjudicated = entry["adjudicated"]
        any_version = adjudicated if adjudicated is not None else filed
        table[frn] = {
            "label": labels.label(entry),
            "applicant_key": keys.applicant_key(any_version),
            # AS COMMITTED: what the fund granted, off the adjudicated version.
            "committed_cents": (
                requests.cents(adjudicated["funding_commitment_request"])
                if adjudicated is not None else ""
            ),
            # AS FILED: what the applicant asked for, off the filed version.
            "filed_months": filed["months_of_service"] if filed is not None else "",
            "filed_commitment_cents": (
                requests.cents(filed["funding_commitment_request"])
                if filed is not None else ""
            ),
            "filed_pre_discount_cents": (
                requests.cents(filed["total_pre_discount_costs"])
                if filed is not None else ""
            ),
            # exactly as the extract writes it
            "filed_discount_pct": filed["dis_pct"] if filed is not None else "",
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
