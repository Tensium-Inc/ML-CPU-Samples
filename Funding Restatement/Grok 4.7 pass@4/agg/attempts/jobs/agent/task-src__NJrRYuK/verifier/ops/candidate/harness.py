#!/usr/bin/env python3
"""Build the funding-request table for the scoring desk.

    python3 harness.py --data-root <DIR> --out <FILE>

Writes csv with one row per distinct funding request.

Deliberately thin. It reads the extract, asks each module its own question and
writes the answers down. The questions live in ``src/`` because that is where
they can be found, argued with and changed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import loading, requests, schema


def build(data_root) -> dict[str, dict]:
    """The table, keyed by funding request number.

    One row per distinct request, including requests that appear as only one
    form version. Filed figures come from the Original version; the commitment
    as granted comes from the Current version. They are the same money column
    and they are not the same number.
    """
    rows = loading.read_rows(data_root)
    grouped = requests.versions(rows)
    table = {}
    for frn, vers in grouped.items():
        table[frn] = requests.fields(
            vers.get(requests.AS_FILED),
            vers.get(requests.AS_ADJUDICATED),
        )
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
