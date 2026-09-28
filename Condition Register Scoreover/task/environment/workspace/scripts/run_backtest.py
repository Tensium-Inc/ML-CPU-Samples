#!/usr/bin/env python3
"""Backtest the scorer on the encounter archive and write results/backtest_report.json."""
from __future__ import annotations

import json
from pathlib import Path

import _bootstrap  # noqa: F401
import pandas as pd
from sklearn.metrics import roc_auc_score

from src import config, features, model

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    cfg = config.require(config.load())
    archive = pd.read_csv(ROOT / cfg["paths"]["encounters"], low_memory=False)

    X = features.build_features(archive, cfg)
    y = features.build_labels(archive).reindex(X.index)

    # Hold out whole patients, never encounters, so one patient cannot sit on both sides.
    patients = features.prepare(archive)["patient_nbr"].reindex(X.index)
    held = set(sorted(patients.unique())[::4])
    is_held = patients.isin(held).values

    clf = model.train(X[~is_held], y[~is_held], cfg)
    auc = float(roc_auc_score(y[is_held], model.score(clf, X[is_held])))

    report = {
        "encounters": int(len(X)),
        "train_rows": int((~is_held).sum()),
        "holdout_rows": int(is_held.sum()),
        "holdout_patients": len(held),
        "label_rate": round(float(y.mean()), 4),
        "mean_conditions": round(float(X["n_conditions"].mean()), 4),
        "holdout_auc": round(auc, 4),
    }
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "backtest_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
