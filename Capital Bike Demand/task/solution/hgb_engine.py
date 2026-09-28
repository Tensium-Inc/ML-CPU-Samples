#!/usr/bin/env python3
"""Independent gradient-boosting solution for the bike forecast task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor


CANONICAL_COLUMNS = [
    "instant", "dteday", "season", "yr", "mnth", "hr", "holiday",
    "weekday", "workingday", "weathersit", "temp", "atemp", "hum",
    "windspeed", "casual", "registered", "cnt",
]
SOURCE_SHA256 = "e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f"
LONG_HORIZON = ("2012_may_aug", "2012-05-01", "2012-09-01")
FOLDS = [
    ("2012_06", "2012-06-01", "2012-07-01"),
    ("2012_07", "2012-07-01", "2012-08-01"),
    ("2012_08", "2012-08-01", "2012-09-01"),
]
BASE_FEATURES = [
    "season", "yr", "mnth", "hr", "holiday", "weekday", "workingday",
    "weathersit", "temp", "atemp", "hum", "windspeed",
]


def load_history(data_dir: str | Path = "data") -> pd.DataFrame:
    root = Path(data_dir)
    registry = json.loads((root / "schema_registry.json").read_text(encoding="ascii"))
    frames = []
    for spec in registry["exports"]:
        frame = pd.read_csv(root / spec["file"], sep=spec["delimiter"])
        frame = frame.rename(columns=spec.get("rename", {}))
        for name, factor in spec.get("scale_to_canonical", {}).items():
            frame[name] = pd.to_numeric(frame[name], errors="raise") * float(factor)
        frames.append(frame[CANONICAL_COLUMNS])
    history = pd.concat(frames, ignore_index=True)
    history["instant"] = pd.to_numeric(history["instant"], errors="raise").astype(int)
    history = history.drop_duplicates("instant", keep="last").sort_values("instant")
    history = history.reset_index(drop=True)
    expected = int(registry["expected_unique_history_rows"])
    if len(history) != expected:
        raise ValueError("history row count mismatch")
    history["dteday"] = pd.to_datetime(history["dteday"], errors="raise")
    for name in CANONICAL_COLUMNS:
        if name != "dteday":
            history[name] = pd.to_numeric(history[name], errors="raise")
    return history


def load_forecast(data_dir: str | Path = "data") -> pd.DataFrame:
    frame = pd.read_csv(Path(data_dir) / "forecast.csv")
    frame["dteday"] = pd.to_datetime(frame["dteday"], errors="raise")
    for name in frame.columns:
        if name != "dteday":
            frame[name] = pd.to_numeric(frame[name], errors="raise")
    return frame


def make_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame[BASE_FEATURES].astype(float).copy()
    hour = result["hr"].to_numpy()
    weekday = result["weekday"].to_numpy()
    month = result["mnth"].to_numpy()
    working = result["workingday"].to_numpy()
    date = pd.to_datetime(frame["dteday"], errors="raise")
    result["hour_sin"] = np.sin(2.0 * np.pi * hour / 24.0)
    result["hour_cos"] = np.cos(2.0 * np.pi * hour / 24.0)
    result["weekday_sin"] = np.sin(2.0 * np.pi * weekday / 7.0)
    result["weekday_cos"] = np.cos(2.0 * np.pi * weekday / 7.0)
    result["month_sin"] = np.sin(2.0 * np.pi * (month - 1.0) / 12.0)
    result["month_cos"] = np.cos(2.0 * np.pi * (month - 1.0) / 12.0)
    result["hour_workingday"] = hour * working
    result["am_commute"] = ((hour >= 7) & (hour <= 9)).astype(float) * working
    result["pm_commute"] = ((hour >= 16) & (hour <= 19)).astype(float) * working
    result["days_since_epoch"] = (date - pd.Timestamp("2011-01-01")).dt.days
    result["temp_humidity"] = result["temp"] * (1.0 - result["hum"])
    return result


class YearBridgeBoosting:
    def __init__(self, seed: int):
        self.model = HistGradientBoostingRegressor(
            loss="poisson",
            learning_rate=0.06,
            max_iter=300,
            max_leaf_nodes=63,
            min_samples_leaf=20,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=seed,
        )

    @staticmethod
    def _scale(X: pd.DataFrame, y: np.ndarray) -> np.ndarray:
        summary = pd.DataFrame({"yr": X["yr"], "mnth": X["mnth"], "y": y})
        means = summary.groupby(["yr", "mnth"])["y"].mean()
        ratios = {
            month: float(means.loc[1, month] / means.loc[0, month])
            for month in sorted(set(summary.loc[summary["yr"] == 1, "mnth"].astype(int)))
            if (0, month) in means.index and means.loc[0, month] > 0
        }
        future = ratios[max(ratios)] if ratios else 1.0
        scale = np.ones(len(X), dtype=float)
        old = X["yr"].to_numpy(dtype=int) == 0
        old_month = X.loc[old, "mnth"].to_numpy(dtype=int)
        scale[old] = [ratios.get(month, future) for month in old_month]
        return scale

    def fit(self, X: pd.DataFrame, y) -> "YearBridgeBoosting":
        target = np.asarray(y, dtype=float)
        scaled = target * self._scale(X, target)
        commute = (
            X["workingday"].eq(1) & X["hr"].isin([7, 8, 9, 16, 17, 18])
        ).to_numpy()
        self.model.fit(X, scaled, sample_weight=np.where(commute, 2.0, 1.0))
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.model.predict(X), dtype=float)


def build_model(seed: int) -> YearBridgeBoosting:
    return YearBridgeBoosting(seed)


def _evaluate(history: pd.DataFrame, spec, seed: int):
    fold_id, start, end = spec
    train = history[history["dteday"] < start]
    valid = history[(history["dteday"] >= start) & (history["dteday"] < end)]
    model = build_model(seed).fit(make_features(train), train["cnt"])
    prediction = np.clip(model.predict(make_features(valid)), 0.0, None)
    error = valid["cnt"].to_numpy(dtype=float) - prediction
    record = {
        "fold_id": fold_id,
        "train_end": train["dteday"].max().strftime("%Y-%m-%d"),
        "eval_start": valid["dteday"].min().strftime("%Y-%m-%d"),
        "eval_end": valid["dteday"].max().strftime("%Y-%m-%d"),
        "eval_rows": int(len(valid)),
        "rmse": round(float(np.sqrt(np.mean(np.square(error)))), 6),
        "mae": round(float(np.mean(np.abs(error))), 6),
    }
    return record, np.abs(error)


def run_backtest(seed: int = 2026, artifact_dir: str | Path = "artifacts"):
    history = load_history().sort_values("instant").reset_index(drop=True)
    long_horizon, _ = _evaluate(history, LONG_HORIZON, seed)
    records = []
    residuals = []
    for offset, spec in enumerate(FOLDS, start=1):
        record, absolute_error = _evaluate(history, spec, seed + offset)
        records.append(record)
        residuals.extend(absolute_error.tolist())
    result = {
        "seed": seed,
        "long_horizon": long_horizon,
        "folds": records,
        "mean_rmse": round(float(np.mean([row["rmse"] for row in records])), 6),
        "max_rmse": round(float(np.max([row["rmse"] for row in records])), 6),
    }
    target = Path(artifact_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "backtest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return result, np.asarray(residuals, dtype=float)


def backtest_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--artifact-dir", default="artifacts")
    args = parser.parse_args()
    result, _ = run_backtest(args.seed, args.artifact_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def final_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="submission.csv")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    history = load_history()
    forecast = load_forecast()
    backtest, residuals = run_backtest(args.seed)
    radius = float(np.quantile(residuals, 0.82))
    train_x = make_features(history)
    forecast_x = make_features(forecast)
    model = build_model(args.seed).fit(train_x, history["cnt"])
    point = np.clip(model.predict(forecast_x), 0.0, None)
    output = pd.DataFrame(
        {
            "instant": forecast["instant"].astype(int),
            "predicted_cnt": point,
            "lower_80": np.clip(point - radius, 0.0, None),
            "upper_80": point + radius,
        }
    ).sort_values("instant")
    output.to_csv(args.output, index=False, lineterminator="\n")
    manifest = {
        "seed": args.seed,
        "history_rows": int(len(history)),
        "forecast_rows": int(len(forecast)),
        "source_sha256": SOURCE_SHA256,
        "model": "year-bridge poisson histogram gradient boosting",
        "features": list(train_x.columns),
        "interval_radius": round(radius, 6),
        "backtest_mean_rmse": backtest["mean_rmse"],
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return 0
