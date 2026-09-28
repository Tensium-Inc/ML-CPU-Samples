#!/usr/bin/env python3
"""Nightly entry point.

    python3 run_scoring.py --config configs/reference.yaml --out out/
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fleetrisk import config, pipeline, report, validate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = config.load(args.config)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scores, fit_df, score_df = pipeline.run(cfg)
    validate.check(scores)

    scores.to_csv(out_dir / "scores.csv", index=False)
    report.write(out_dir / "run_report.json",
                 report.summarise(scores, cfg))
    print("scored %d rows, watching %d" % (len(scores), int(scores["watch"].sum())))


if __name__ == "__main__":
    main()
