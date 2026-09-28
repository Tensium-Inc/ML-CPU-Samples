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

    The extract records form versions, not requests: `Original` is the request
    AS FILED and `Current` is the same request AS ADJUDICATED, and the two do
    not carry the same numbers. Each field is read off the version that carries
    the fact it reports:

      * the filed_* fields come off the Original version -- what the applicant
        asked for, before review touched it;
      * committed_cents comes off the Current version -- what the fund granted;
      * the label is a reading of the adjudicated version's own record of what
        happened (money committed and a funding wave), not of the letter's
        wording, and a request with no adjudicated version is undecided.

    A version the extract does not carry leaves its fields with nothing to
    report, which is the empty string and never a zero.
    """
    rows = loading.read_rows(data_root)
    table: dict[str, dict] = {}
    for frn, versions in requests.collect(rows).items():
        filed = versions.get(requests.FILED)
        adjudicated = versions.get(requests.ADJUDICATED)
        any_version = adjudicated or filed
        table[frn] = {
            "label": labels.label(adjudicated),
            "applicant_key": keys.applicant_key(any_version),
            "committed_cents": (
                requests.cents(adjudicated["funding_commitment_request"])
                if adjudicated else ""),
            "filed_months": filed["months_of_service"] if filed else "",
            "filed_commitment_cents": (
                requests.cents(filed["funding_commitment_request"])
                if filed else ""),
            "filed_pre_discount_cents": (
                requests.cents(filed["total_pre_discount_costs"])
                if filed else ""),
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
