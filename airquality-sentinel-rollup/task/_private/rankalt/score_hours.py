#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
import pandas as pd
import yaml

from src import channels, features, model, serve

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    window = int(cfg["alerting"]["rolling_window_hours"])

    archive = channels.read_log(ROOT / cfg["paths"]["history"])
    X = features.build_features(archive, window)
    y = features.build_labels(archive, cfg["alerting"]["target"],
                              float(cfg["alerting"]["threshold"])).reindex(X.index)
    clf = model.train(X, y, cfg)

    batch = channels.read_log(args.batch)
    frame = serve.build_serving_frame(batch, window)
    scores = model.score(clf, frame).rank(pct=True).clip(0.0, 1.0)

    out = pd.DataFrame({"timestamp": frame.index, "alert_probability": scores.values,
                        "rollup_24h": frame["rollup_24h"].values})
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.sort_values("timestamp").to_csv(dest, index=False)
    print(f"scored {len(out)} hours -> {dest}")


if __name__ == "__main__":
    main()
