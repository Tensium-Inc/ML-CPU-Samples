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
    """The table, keyed by funding request number."""
    rows = loading.read_rows(data_root)
    chosen = requests.collect(rows)
    return {
        frn: {
            "label": labels.label(row),
            "applicant_key": keys.applicant_key(row),
            "filed_commitment_cents": requests.cents(row["funding_commitment_request"]),
            "filed_pre_discount_cents": requests.cents(row["total_pre_discount_costs"]),
            "filed_discount_pct": row["dis_pct"],
            # TODO(desk): the deliverable note says these two are read off
            # DIFFERENT versions of the request from each other. Both are taken
            # off the same row here, which cannot be right for both.
            "committed_cents": requests.cents(row["funding_commitment_request"]),
            "filed_months": row["months_of_service"],
        }
        for frn, row in chosen.items()
    }


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
