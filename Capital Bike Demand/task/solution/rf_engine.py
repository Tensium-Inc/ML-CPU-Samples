#!/usr/bin/env python3
"""Independent random-forest solution for the bike forecast task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor


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
RAW_FEATURES = [
    "season", "yr", "mnth", "hr", "holiday", "weekday", "workingday",
    "weathersit", "temp", "atemp", "hum", "windspeed",
]


def load_history(data_dir: str | Path = "data") -> pd.DataFrame:
    root = Path(data_dir)
    registry = json.loads((root / "schema_registry.json").read_text(encoding="ascii"))
    specs = registry["exports"]
    normalized = []
    for spec in specs:
        part = pd.read_csv(root / spec["file"], delimiter=spec["delimiter"])
        if len(part) != int(spec["expected_raw_rows"]):
            raise ValueError(f"unexpected export size: {spec['file']}")
        part.rename(columns=spec.get("rename", {}), inplace=True)
        for column, multiplier in spec.get("scale_to_canonical", {}).items():
            part[column] = part[column].astype(float) * float(multiplier)
        normalized.append(part.reindex(columns=CANONICAL_COLUMNS))
    result = pd.concat(normalized, axis=0, ignore_index=True)
    result["instant"] = result["instant"].astype(int)
    result = result.sort_values("instant").drop_duplicates("instant", keep="last")
    result = result.reset_index(drop=True)
    if result.shape != (int(registry["expected_unique_history_rows"]), len(CANONICAL_COLUMNS)):
        raise ValueError("canonical history shape mismatch")
    result["dteday"] = pd.to_datetime(result["dteday"], format="%Y-%m-%d")
    numeric = [column for column in CANONICAL_COLUMNS if column != "dteday"]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="raise")
    return result


def load_forecast(data_dir: str | Path = "data") -> pd.DataFrame:
    result = pd.read_csv(Path(data_dir) / "forecast.csv")
    result["dteday"] = pd.to_datetime(result["dteday"], format="%Y-%m-%d")
    numeric = [column for column in result if column != "dteday"]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="raise")
    return result


def make_features(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame[RAW_FEATURES].astype(float).copy()
    date = pd.to_datetime(frame["dteday"], errors="raise")
    output["day"] = date.dt.day.astype(float)
    output["day_of_year"] = date.dt.dayofyear.astype(float)
    output["week_of_year"] = date.dt.isocalendar().week.to_numpy(dtype=float)
    output["rush_hour"] = output["hr"].isin([7, 8, 9, 16, 17, 18]).astype(float)
    output["working_rush"] = output["rush_hour"] * output["workingday"]
    output["hour_working"] = output["hr"] + 24.0 * output["workingday"]
    output["weather_hour"] = 24.0 * output["weathersit"] + output["hr"]
    output["annual_sin"] = np.sin(2.0 * np.pi * output["day_of_year"] / 366.0)
    output["annual_cos"] = np.cos(2.0 * np.pi * output["day_of_year"] / 366.0)
    return output


class CappedGrowthForest:
    def __init__(self, seed: int):
        self.forest = RandomForestRegressor(
            n_estimators=240,
            min_samples_leaf=1,
            max_features=0.9,
            n_jobs=2,
            random_state=seed,
        )

    @staticmethod
    def _bridge_target(X: pd.DataFrame, y: np.ndarray) -> np.ndarray:
        table = pd.DataFrame({"year": X["yr"], "month": X["mnth"], "target": y})
        means = table.groupby(["year", "month"])["target"].mean()
        ratios = {}
        for month in sorted(table.loc[table["year"] == 1, "month"].astype(int).unique()):
            if (0, month) in means.index and means.loc[(0, month)] > 0:
                raw_ratio = float(means.loc[(1, month)] / means.loc[(0, month)])
                ratios[month] = float(np.clip(raw_ratio, 1.2, 1.65))
        carry = ratios[max(ratios)] if ratios else 1.0
        multiplier = np.ones(len(table), dtype=float)
        old_positions = np.flatnonzero(table["year"].to_numpy(dtype=int) == 0)
        for position in old_positions:
            month = int(table.iloc[position]["month"])
            multiplier[position] = ratios.get(month, carry)
        return y * multiplier

    def fit(self, X: pd.DataFrame, y) -> "CappedGrowthForest":
        target = np.asarray(y, dtype=float)
        bridged = self._bridge_target(X, target)
        commute = (
            X["workingday"].eq(1) & X["hr"].isin([7, 8, 9, 16, 17, 18])
        ).to_numpy()
        self.forest.fit(X, bridged, sample_weight=np.where(commute, 2.0, 1.0))
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.forest.predict(X), dtype=float)


def build_model(seed: int) -> CappedGrowthForest:
    return CappedGrowthForest(seed)


def score_window(history: pd.DataFrame, window, seed: int):
    name, start, stop = window
    train = history.loc[history["dteday"] < start]
    valid = history.loc[(history["dteday"] >= start) & (history["dteday"] < stop)]
    prediction = build_model(seed).fit(make_features(train), train["cnt"]).predict(
        make_features(valid)
    )
    prediction = np.maximum(prediction, 0.0)
    residual = valid["cnt"].to_numpy(dtype=float) - prediction
    metrics = {
        "fold_id": name,
        "train_end": train["dteday"].iloc[-1].strftime("%Y-%m-%d"),
        "eval_start": valid["dteday"].iloc[0].strftime("%Y-%m-%d"),
        "eval_end": valid["dteday"].iloc[-1].strftime("%Y-%m-%d"),
        "eval_rows": int(valid.shape[0]),
        "rmse": round(float(np.sqrt(np.mean(residual ** 2))), 6),
        "mae": round(float(np.mean(np.abs(residual))), 6),
    }
    return metrics, np.abs(residual)


def run_backtest(seed: int = 2026, artifact_dir: str | Path = "artifacts"):
    history = load_history().sort_values("instant").reset_index(drop=True)
    horizon, _ = score_window(history, LONG_HORIZON, seed)
    folds = []
    calibration_parts = []
    for offset, window in enumerate(FOLDS, start=1):
        metrics, absolute_residual = score_window(history, window, seed + offset)
        folds.append(metrics)
        calibration_parts.append(absolute_residual)
    document = {
        "seed": seed,
        "long_horizon": horizon,
        "folds": folds,
        "mean_rmse": round(float(np.mean([fold["rmse"] for fold in folds])), 6),
        "max_rmse": round(float(max(fold["rmse"] for fold in folds)), 6),
    }
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "backtest.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return document, np.concatenate(calibration_parts)


def backtest_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--artifact-dir", default="artifacts")
    options = parser.parse_args()
    document, _ = run_backtest(options.seed, options.artifact_dir)
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


def final_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="submission.csv")
    parser.add_argument("--seed", type=int, default=2026)
    options = parser.parse_args()
    history = load_history()
    forecast = load_forecast()
    backtest, calibration = run_backtest(options.seed)
    radius = float(np.quantile(calibration, 0.82))
    train_features = make_features(history)
    model = build_model(options.seed).fit(train_features, history["cnt"])
    point = np.maximum(model.predict(make_features(forecast)), 0.0)
    result = pd.DataFrame(
        {
            "instant": forecast["instant"].astype(int),
            "predicted_cnt": point,
            "lower_80": np.maximum(point - radius, 0.0),
            "upper_80": point + radius,
        }
    ).sort_values("instant")
    result.to_csv(options.output, index=False, lineterminator="\n")
    manifest = {
        "seed": options.seed,
        "history_rows": int(history.shape[0]),
        "forecast_rows": int(forecast.shape[0]),
        "source_sha256": SOURCE_SHA256,
        "model": "capped year-bridge random forest",
        "features": train_features.columns.tolist(),
        "interval_radius": round(radius, 6),
        "backtest_mean_rmse": backtest["mean_rmse"],
    }
    Path("artifacts/run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return 0
