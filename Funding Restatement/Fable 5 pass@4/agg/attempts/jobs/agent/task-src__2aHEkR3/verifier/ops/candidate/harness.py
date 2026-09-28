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

    The extract carries up to two versions of every request and they do not
    carry the same numbers, so each field is read off the version it belongs
    to:

      * `committed_cents` is the money column AS COMMITTED -- the adjudicated
        (`Current`) version.
      * every `filed_*` field is AS FILED -- the `Original` version, before
        review restated it.
      * the label is a judgement about what the fund did and is settled on the
        adjudicated version (see `labels`).

    A version the extract does not carry has nothing to report: those fields
    are the empty string, never a zero -- they are different facts.
    """
    rows = loading.read_rows(data_root)
    table: dict[str, dict] = {}
    for frn, versions in requests.collect(rows).items():
        original = versions.get("Original")
        current = versions.get("Current")
        table[frn] = {
            "label": labels.label(current),
            "applicant_key": keys.applicant_key(current or original),
            "committed_cents": requests.cents(current["funding_commitment_request"]) if current else "",
            "filed_months": original["months_of_service"] if original else "",
            "filed_commitment_cents": requests.cents(original["funding_commitment_request"]) if original else "",
            "filed_pre_discount_cents": requests.cents(original["total_pre_discount_costs"]) if original else "",
            "filed_discount_pct": original["dis_pct"] if original else "",
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
