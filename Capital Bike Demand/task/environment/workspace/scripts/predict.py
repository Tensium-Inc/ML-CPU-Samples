#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.data import load_requests, load_runtime_history
from pipeline.forecast import predict_frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", required=True)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    result = predict_frame(load_runtime_history(args.history), load_requests(args.requests), args.seed)
    result.to_csv(args.output, index=False, lineterminator="\n", float_format="%.12g")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
