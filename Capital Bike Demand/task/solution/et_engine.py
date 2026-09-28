#!/usr/bin/env python3
"""Independent CSV and extra-trees solution for the bike forecast task."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor


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
INPUT_FEATURES = [
    "season", "yr", "mnth", "hr", "holiday", "weekday", "workingday",
    "weathersit", "temp", "atemp", "hum", "windspeed",
]


def _typed_frame(rows: list[dict[str, str]], columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(rows, columns=columns)
    frame["dteday"] = pd.to_datetime(frame["dteday"], format="%Y-%m-%d")
    numeric = [column for column in columns if column != "dteday"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="raise")
    return frame


def load_history(data_dir: str | Path = "data") -> pd.DataFrame:
    root = Path(data_dir)
    registry = json.loads((root / "schema_registry.json").read_text(encoding="ascii"))
    records: list[dict[str, str]] = []
    for spec in registry["exports"]:
        rename = spec.get("rename", {})
        with (root / spec["file"]).open(encoding="ascii", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=spec["delimiter"])
            part = []
            for raw in reader:
                canonical = {rename.get(name, name): value for name, value in raw.items()}
                for name, factor in spec.get("scale_to_canonical", {}).items():
                    canonical[name] = str(float(canonical[name]) * float(factor))
                part.append({name: canonical[name] for name in CANONICAL_COLUMNS})
        if len(part) != int(spec["expected_raw_rows"]):
            raise ValueError(f"bad row count in {spec['file']}")
        records.extend(part)
    frame = _typed_frame(records, CANONICAL_COLUMNS)
    frame["instant"] = frame["instant"].astype(int)
    frame = frame.drop_duplicates("instant", keep="last")
    frame = frame.sort_values("instant").reset_index(drop=True)
    if len(frame) != int(registry["expected_unique_history_rows"]):
        raise ValueError("deduplicated history row count mismatch")
    return frame


def load_forecast(data_dir: str | Path = "data") -> pd.DataFrame:
    path = Path(data_dir) / "forecast.csv"
    with path.open(encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    return _typed_frame(rows, columns)


def make_features(frame: pd.DataFrame) -> pd.DataFrame:
    matrix = frame[INPUT_FEATURES].astype(float).copy()
    dates = pd.to_datetime(frame["dteday"], errors="raise")
    matrix["day"] = dates.dt.day.astype(float)
    matrix["day_of_year"] = dates.dt.dayofyear.astype(float)
    matrix["week_of_year"] = dates.dt.isocalendar().week.to_numpy(dtype=float)
    matrix["rush_hour"] = matrix["hr"].isin([7, 8, 9, 16, 17, 18]).astype(float)
    matrix["working_rush"] = matrix["rush_hour"] * matrix["workingday"]
    matrix["hour_working"] = matrix["hr"] + 24.0 * matrix["workingday"]
    matrix["weather_hour"] = matrix["hr"] + 24.0 * matrix["weathersit"]
    phase = 2.0 * np.pi * matrix["day_of_year"] / 366.0
    matrix["annual_sin"] = np.sin(phase)
    matrix["annual_cos"] = np.cos(phase)
    return matrix


class CappedGrowthExtraTrees:
    def __init__(self, seed: int):
        self.estimator = ExtraTreesRegressor(
            n_estimators=240,
            min_samples_leaf=2,
            max_features=1.0,
            n_jobs=2,
            random_state=seed,
        )

    @staticmethod
    def _adjust_older_year(X: pd.DataFrame, target: np.ndarray) -> np.ndarray:
        keys = pd.MultiIndex.from_arrays(
            [X["yr"].astype(int), X["mnth"].astype(int)], names=["yr", "mnth"]
        )
        monthly = pd.Series(target, index=keys).groupby(level=[0, 1]).mean()
        ratios: dict[int, float] = {}
        observed_months = sorted(X.loc[X["yr"] == 1, "mnth"].astype(int).unique())
        for month in observed_months:
            if (0, month) in monthly.index:
                ratio = float(monthly.loc[(1, month)] / monthly.loc[(0, month)])
                ratios[month] = float(np.clip(ratio, 1.2, 1.65))
        carry = ratios[max(ratios)] if ratios else 1.0
        factors = np.ones(len(X), dtype=float)
        for index, (year, month) in enumerate(zip(X["yr"], X["mnth"])):
            if int(year) == 0:
                factors[index] = ratios.get(int(month), carry)
        return target * factors

    def fit(self, X: pd.DataFrame, y) -> "CappedGrowthExtraTrees":
        target = np.asarray(y, dtype=float)
        target = self._adjust_older_year(X, target)
        is_commute = (
            X["workingday"].eq(1) & X["hr"].isin([7, 8, 9, 16, 17, 18])
        ).to_numpy()
        weights = np.where(is_commute, 2.0, 1.0)
        self.estimator.fit(X, target, sample_weight=weights)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.estimator.predict(X), dtype=float)


def build_model(seed: int) -> CappedGrowthExtraTrees:
    return CappedGrowthExtraTrees(seed)


def _fold(history: pd.DataFrame, definition, seed: int):
    fold_id, first_day, next_day = definition
    before = history[history["dteday"] < first_day]
    during = history[
        (history["dteday"] >= first_day) & (history["dteday"] < next_day)
    ]
    fitted = build_model(seed)
    fitted.fit(make_features(before), before["cnt"].to_numpy(dtype=float))
    estimate = np.clip(fitted.predict(make_features(during)), 0.0, None)
    difference = during["cnt"].to_numpy(dtype=float) - estimate
    report = {
        "fold_id": fold_id,
        "train_end": before["dteday"].max().strftime("%Y-%m-%d"),
        "eval_start": during["dteday"].min().strftime("%Y-%m-%d"),
        "eval_end": during["dteday"].max().strftime("%Y-%m-%d"),
        "eval_rows": int(len(during)),
        "rmse": round(float(np.sqrt(np.mean(np.square(difference)))), 6),
        "mae": round(float(np.mean(np.abs(difference))), 6),
    }
    return report, np.abs(difference)


def run_backtest(seed: int = 2026, artifact_dir: str | Path = "artifacts"):
    history = load_history()
    long_report, _ = _fold(history, LONG_HORIZON, seed)
    fold_reports = []
    absolute_errors = []
    for number, definition in enumerate(FOLDS, start=1):
        report, errors = _fold(history, definition, seed + number)
        fold_reports.append(report)
        absolute_errors.append(errors)
    rmse_values = [item["rmse"] for item in fold_reports]
    artifact = {
        "seed": seed,
        "long_horizon": long_report,
        "folds": fold_reports,
        "mean_rmse": round(float(np.mean(rmse_values)), 6),
        "max_rmse": round(float(np.max(rmse_values)), 6),
    }
    directory = Path(artifact_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "backtest.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return artifact, np.concatenate(absolute_errors)


def backtest_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--artifact-dir", default="artifacts")
    arguments = parser.parse_args()
    artifact, _ = run_backtest(arguments.seed, arguments.artifact_dir)
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0


def final_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="submission.csv")
    parser.add_argument("--seed", type=int, default=2026)
    arguments = parser.parse_args()
    history = load_history()
    forecast = load_forecast()
    backtest, absolute_errors = run_backtest(arguments.seed)
    radius = float(np.quantile(absolute_errors, 0.82))
    train_matrix = make_features(history)
    fitted = build_model(arguments.seed).fit(train_matrix, history["cnt"])
    forecast_value = np.clip(fitted.predict(make_features(forecast)), 0.0, None)
    submission = pd.DataFrame(
        {
            "instant": forecast["instant"].astype(int),
            "predicted_cnt": forecast_value,
            "lower_80": np.clip(forecast_value - radius, 0.0, None),
            "upper_80": forecast_value + radius,
        }
    ).sort_values("instant")
    submission.to_csv(arguments.output, index=False, lineterminator="\n")
    manifest = {
        "seed": arguments.seed,
        "history_rows": int(len(history)),
        "forecast_rows": int(len(forecast)),
        "source_sha256": SOURCE_SHA256,
        "model": "capped year-bridge extra trees",
        "features": list(train_matrix.columns),
        "interval_radius": round(radius, 6),
        "backtest_mean_rmse": backtest["mean_rmse"],
    }
    Path("artifacts/run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return 0
