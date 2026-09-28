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

from src import loading, requests, schema


def build(data_root) -> dict[str, dict]:
    """The table, keyed by funding request number.

    Filed figures are read off the as-filed version of the request and the
    commitment off the adjudicated version. They are the same money column and
    they are not the same number, so both versions are kept and each field is
    taken from the version it belongs to.
    """
    rows = loading.read_rows(data_root)
    return requests.build_table(rows)


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
