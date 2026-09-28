#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    b = pd.read_csv(a.batch, low_memory=False)
    b["timestamp"] = pd.to_datetime(b["timestamp"])
    s = b["PT08.S1(CO)"].astype(float)
    out = pd.DataFrame({"timestamp": b["timestamp"],
                        "alert_probability": s.rank(pct=True).clip(0, 1),
                        "rollup_24h": s.rolling(24, min_periods=1).mean()})
    dest = Path(a.out); dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest, index=False)

if __name__ == "__main__":
    main()
