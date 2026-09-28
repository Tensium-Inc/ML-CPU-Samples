#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
import pandas as pd
import yaml

from src import channels, features, model, rollup, serve

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="hourly batch to score")
    ap.add_argument("--out", required=True, help="destination csv")
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
    scores = model.score(clf, frame)

    station_log = pd.concat([archive[batch.columns], batch], ignore_index=True)
    station_log = station_log.drop_duplicates("timestamp").sort_values("timestamp", kind="stable")
    display = rollup.build_rollups(station_log, window)["rollup_24h"]

    out = pd.DataFrame({"timestamp": frame.index, "alert_probability": scores.values,
                        "rollup_24h": display.reindex(frame.index).values})
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.sort_values("timestamp").to_csv(dest, index=False)
    print(f"scored {len(out)} hours -> {dest}")


if __name__ == "__main__":
    main()
