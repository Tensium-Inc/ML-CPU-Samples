#!/usr/bin/env python3
"""Diff two score files by flight_id.

    python3 tools/compare_scores.py a/scores.csv b/scores.csv
"""
import argparse

import pandas as pd

TOLERANCE = 1e-6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("left")
    ap.add_argument("right")
    args = ap.parse_args()
    left = pd.read_csv(args.left)
    right = pd.read_csv(args.right)
    merged = left[["flight_id", "risk_score"]].merge(
        right[["flight_id", "risk_score"]], on="flight_id", how="outer",
        suffixes=("_left", "_right"))
    diff = (merged["risk_score_left"] - merged["risk_score_right"]).abs()
    same = (diff <= TOLERANCE).fillna(False)
    print("rows %d, agree %d (%.6f), max abs diff %.6g"
          % (len(merged), int(same.sum()), same.mean(), float(diff.max())))
    worst = merged.assign(diff=diff).sort_values("diff", ascending=False).head(10)
    print(worst.to_string(index=False))


if __name__ == "__main__":
    main()
