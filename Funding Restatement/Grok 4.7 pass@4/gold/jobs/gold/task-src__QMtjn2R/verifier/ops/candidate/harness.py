#!/usr/bin/env python3
"""Funding-request table -- entry point.

Rebuilt to the ops notes. Nothing is decided here: the command line, the order
the passes run in and where the rows go is all this file does.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import keys, labels, loading, requests, schema


def build(data_root):
    rows = loading.read_rows(data_root)
    table = {}
    for frn, pair in requests.collect(rows).items():
        filed, adjudicated = pair["filed"], pair["adjudicated"]
        table[frn] = {
            "label": labels.label(adjudicated),
            "applicant_key": keys.applicant_key(filed or adjudicated),
            "filed_commitment_cents":
                requests.cents(filed["funding_commitment_request"]) if filed else "",
            "filed_pre_discount_cents":
                requests.cents(filed["total_pre_discount_costs"]) if filed else "",
            "filed_discount_pct": (filed["dis_pct"] if filed else ""),
            # Read off the ADJUDICATED row, not the filed one. It is the same
            # money column and a different number on 13,585 requests.
            "committed_cents":
                requests.cents(adjudicated["funding_commitment_request"]) if adjudicated else "",
            "filed_months": (filed["months_of_service"] if filed else ""),
        }
    return table


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    table = build(a.data_root)
    schema.write(table, Path(a.out))
    print(f"built {len(table):,} requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
