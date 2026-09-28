#!/usr/bin/env python3
"""Run the desk's local check against the harness in this workspace.

    python3 check_report.py --data-root data

Builds the table, fits the scorer over whatever population the harness produced,
holds out whole applicants, and prints the AUC quoted in a release request.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness
from src import loading, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default="data")
    opts = ap.parse_args()
    rows = loading.read_rows(opts.data_root)
    print(json.dumps(report.holdout_auc(rows, harness.build(opts.data_root)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
