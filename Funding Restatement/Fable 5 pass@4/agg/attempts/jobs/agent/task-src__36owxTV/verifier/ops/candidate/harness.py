#!/usr/bin/env python3
"""Build the funding-request table for the scoring desk.

    python3 harness.py --data-root <DIR> --out <FILE>

Writes csv with one row per distinct funding request.

Deliberately thin. It reads the extract, asks each module its own question and
writes the answers down. The questions live in `src/` because that is where they
can be found, argued with and changed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import keys, labels, loading, requests, schema


def build(data_root) -> dict[str, dict]:
    """The table, keyed by funding request number.

    Every field is read off the version of the request that carries the fact it
    reports. The `filed_*` fields are the request AS FILED and come off the
    Original version; `committed_cents` is what the fund granted and comes off
    the Current (adjudicated) version. They are the same money column of the
    extract and they are not the same number. A request missing a version has
    nothing to report for that version's fields, and reports the empty string --
    never a zero, which is a different fact.
    """
    rows = loading.read_rows(data_root)
    table: dict[str, dict] = {}
    for frn, versions in requests.collect(rows).items():
        filed = versions.get(requests.ORIGINAL)
        adjudicated = versions.get(requests.CURRENT)
        table[frn] = {
            "label": labels.label(versions),
            "applicant_key": keys.applicant_key(versions),
            # As committed: the adjudicated version's account of the money.
            "committed_cents": (
                requests.cents(adjudicated["funding_commitment_request"])
                if adjudicated else ""),
            # As filed: the Original version's account, verbatim where the
            # deliverable asks for the extract's own spelling.
            "filed_months": filed["months_of_service"] if filed else "",
            "filed_commitment_cents": (
                requests.cents(filed["funding_commitment_request"]) if filed else ""),
            "filed_pre_discount_cents": (
                requests.cents(filed["total_pre_discount_costs"]) if filed else ""),
            "filed_discount_pct": filed["dis_pct"] if filed else "",
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
