#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path

import _bootstrap  # noqa: F401
import pandas as pd
import yaml
from sklearn.metrics import roc_auc_score

from src import channels, features, model

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    log = channels.read_log(ROOT / cfg["paths"]["history"])
    window = int(cfg["alerting"]["rolling_window_hours"])

    X = features.build_features(log, window)
    y = features.build_labels(log, cfg["alerting"]["target"], float(cfg["alerting"]["threshold"]))
    y = y.reindex(X.index)

    # Hold out the last quarter of the archive, so the split respects time.
    cut = int(len(X) * 0.75)
    Xtr, Xte, ytr, yte = X.iloc[:cut], X.iloc[cut:], y.iloc[:cut], y.iloc[cut:]

    clf = model.train(Xtr, ytr, cfg)
    auc = float(roc_auc_score(yte, model.score(clf, Xte)))

    report = {
        "hours": int(len(X)),
        "train_hours": int(len(Xtr)),
        "holdout_hours": int(len(Xte)),
        "alert_rate": round(float(y.mean()), 4),
        "holdout_auc": round(auc, 4),
    }
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "backtest_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
