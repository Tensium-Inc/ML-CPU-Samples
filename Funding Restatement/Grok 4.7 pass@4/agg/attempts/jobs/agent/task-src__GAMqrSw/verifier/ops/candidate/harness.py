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

    The harness exists to score a request for whether it will be funded, from
    what was knowable when it was filed. Adjudication restates the numbers, so
    the filed fields and the commitment are not read off the same version:

      filed_*     Original, the request as the applicant filed it. A request
                  that was never captured as filed has nothing to report for
                  these -- a blank, not the restated number and not a zero.
      committed   Current, what the fund actually granted. A request nobody
                  has adjudicated has no commitment to report.
      label       whether that grant was made, not what a status token says.
      applicant   the billed entity, which does not move between versions.
    """
    rows = loading.read_rows(data_root)
    by_version = requests.versions(rows)
    table: dict[str, dict] = {}
    for frn, vers in by_version.items():
        filed = vers.get("Original")
        committed = vers.get("Current")
        identity = committed or filed
        table[frn] = {
            "label": labels.label(committed),
            "applicant_key": keys.applicant_key(identity),
            "committed_cents": requests.cents(
                committed["funding_commitment_request"] if committed else ""
            ),
            "filed_months": filed["months_of_service"] if filed else "",
            "filed_commitment_cents": requests.cents(
                filed["funding_commitment_request"] if filed else ""
            ),
            "filed_pre_discount_cents": requests.cents(
                filed["total_pre_discount_costs"] if filed else ""
            ),
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
