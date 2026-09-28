#!/usr/bin/env python3
"""Score one encounter batch and write the export the network receives."""
from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
import pandas as pd

from src import config, features, model, serve

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="encounter batch to score")
    ap.add_argument("--out", required=True, help="destination csv")
    args = ap.parse_args()

    cfg = config.require(config.load())

    archive = pd.read_csv(ROOT / cfg["paths"]["encounters"], low_memory=False)
    X = features.build_features(archive, cfg)
    y = features.build_labels(archive).reindex(X.index)
    clf = model.train(X, y, cfg)

    batch = pd.read_csv(args.batch, low_memory=False)
    frame = serve.build_serving_frame(batch, cfg)
    scores = model.score(clf, frame)
    out = serve.scored_rows(batch, scores, cfg)

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest, index=False)
    print(f"scored {len(batch)} encounters -> {dest} ({len(out)} rows)")


if __name__ == "__main__":
    main()
