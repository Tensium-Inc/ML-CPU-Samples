#!/usr/bin/env python3
"""Replay the frozen bike forecast candidate over verifier-owned terminal labels."""
from __future__ import annotations

import json
import math
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STATE_DIR = Path("/var/lib/capital-bike-task")
CANDIDATE = STATE_DIR / "terminal_candidate"
HISTORY = STATE_DIR / "terminal_history.csv"
LABELS = STATE_DIR / "verifier_terminal.csv"
DELIVERABLE = Path("/workspace/target/terminal-predictions.csv")
RUN_USER = "ubuntu"
OUTPUT_COLUMNS = ["instant", "predicted_cnt", "lower_80", "upper_80"]


def _identity() -> dict[str, str]:
    if os.geteuid() != 0:
        return {}
    account = pwd.getpwnam(RUN_USER)
    return {"user": account.pw_name, "group": account.pw_name}


def _load_output(path: Path, expected_ids: set[int]) -> tuple[pd.DataFrame | None, str]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
        return None, "output_missing_or_unsafe"
    try:
        raw = path.read_bytes()
        raw.decode("ascii")
        frame = pd.read_csv(path)
    except Exception:
        return None, "output_parse"
    if list(frame.columns) != OUTPUT_COLUMNS or len(frame) != len(expected_ids):
        return None, "output_contract"
    try:
        numeric = frame[OUTPUT_COLUMNS].apply(pd.to_numeric, errors="raise")
    except Exception:
        return None, "output_numeric"
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        return None, "output_nonfinite"
    ids = numeric["instant"].to_numpy(dtype=float)
    if not np.allclose(ids, np.rint(ids), rtol=0.0, atol=0.0):
        return None, "output_identity_type"
    frame["instant"] = np.rint(ids).astype(int)
    frame[OUTPUT_COLUMNS[1:]] = numeric[OUTPUT_COLUMNS[1:]].astype(float)
    if frame["instant"].duplicated().any() or set(frame["instant"]) != expected_ids:
        return None, "output_identity_coverage"
    if (
        (frame["predicted_cnt"] < 0.0).any()
        or (frame["lower_80"] < 0.0).any()
        or (frame["lower_80"] > frame["predicted_cnt"]).any()
        or (frame["predicted_cnt"] > frame["upper_80"]).any()
    ):
        return None, "output_interval_contract"
    return frame.sort_values("instant").reset_index(drop=True), "ok"


def _run(seed: int) -> tuple[pd.DataFrame | None, str]:
    labels = pd.read_csv(LABELS)
    requests = labels.drop(columns=["casual", "registered", "cnt"])
    history = pd.read_csv(HISTORY)
    if seed:
        history = history.sample(frac=1.0, random_state=seed).reset_index(drop=True)
        requests = requests.sample(frac=1.0, random_state=seed + 1).reset_index(drop=True)
    run = Path(tempfile.mkdtemp(prefix="bike-terminal-", dir="/tmp"))
    candidate_dir = run / "candidate"
    history_path = run / "history.csv"
    requests_path = run / "requests.csv"
    output_path = run / "output.csv"
    try:
        shutil.copytree(CANDIDATE, candidate_dir)
        history.to_csv(history_path, index=False, lineterminator="\n")
        requests.to_csv(requests_path, index=False, lineterminator="\n")
        account = pwd.getpwnam(RUN_USER)
        for path in (run, *run.rglob("*")):
            os.chown(path, account.pw_uid, account.pw_gid)
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(run),
            "TMPDIR": str(run),
            "LANG": "C.UTF-8",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
        try:
            process = subprocess.run(
                [
                    sys.executable,
                    str(candidate_dir / "scripts" / "predict.py"),
                    "--history",
                    str(history_path),
                    "--requests",
                    str(requests_path),
                    "--output",
                    str(output_path),
                    "--seed",
                    "2026",
                ],
                cwd=str(candidate_dir),
                env=environment,
                text=True,
                capture_output=True,
                timeout=300,
                check=False,
                **_identity(),
            )
        except subprocess.TimeoutExpired:
            return None, "candidate_timeout"
        if process.returncode != 0:
            return None, "candidate_runtime"
        return _load_output(output_path, set(labels["instant"].astype(int)))
    finally:
        shutil.rmtree(run, ignore_errors=True)


def _metrics(output: pd.DataFrame, labels: pd.DataFrame) -> tuple[bool, dict[str, Any]]:
    joined = labels.merge(output, on="instant", how="inner").sort_values("instant")
    actual = joined["cnt"].to_numpy(dtype=float)
    error = output["predicted_cnt"].to_numpy(dtype=float) - actual
    rmse = float(np.sqrt(np.mean(np.square(error))))
    dates = pd.to_datetime(joined["dteday"], errors="raise")
    month_rmse = {}
    for month in sorted(dates.dt.month.unique()):
        mask = dates.dt.month.to_numpy() == month
        month_rmse[str(int(month))] = float(np.sqrt(np.mean(np.square(error[mask]))))
    commute = (
        joined["workingday"].eq(1)
        & joined["hr"].isin([7, 8, 9, 16, 17, 18])
    ).to_numpy()
    commute_mae = float(np.mean(np.abs(error[commute])))
    lower = output["lower_80"].to_numpy(dtype=float)
    upper = output["upper_80"].to_numpy(dtype=float)
    coverage = float(np.mean((actual >= lower) & (actual <= upper)))
    mean_width = float(np.mean(upper - lower))
    healthy = (
        rmse <= 65.0
        and max(month_rmse.values()) <= 72.0
        and commute_mae <= 76.0
        and 0.70 <= coverage <= 0.98
        and mean_width <= 250.0
    )
    return healthy, {
        "overall_rmse": round(rmse, 6),
        "month_rmse": {name: round(value, 6) for name, value in month_rmse.items()},
        "commute_mae": round(commute_mae, 6),
        "coverage": round(coverage, 6),
        "mean_width": round(mean_width, 6),
    }


def main() -> int:
    try:
        labels = pd.read_csv(LABELS).sort_values("instant").reset_index(drop=True)
        first, first_reason = _run(0)
        second, second_reason = _run(404)
        delivered, delivered_reason = _load_output(DELIVERABLE, set(labels["instant"].astype(int)))
        if first is None or second is None or delivered is None:
            payload = {
                "healthy": False,
                "reason": f"replay:{first_reason}:{second_reason}:{delivered_reason}",
            }
        else:
            invariant = first["instant"].equals(second["instant"]) and np.allclose(
                first[OUTPUT_COLUMNS[1:]], second[OUTPUT_COLUMNS[1:]], rtol=1e-8, atol=1e-8
            )
            bound = first["instant"].equals(delivered["instant"]) and np.allclose(
                first[OUTPUT_COLUMNS[1:]], delivered[OUTPUT_COLUMNS[1:]], rtol=1e-7, atol=1e-6
            )
            values_ok, metrics = _metrics(first, labels)
            payload = {
                "healthy": bool(invariant and bound and values_ok),
                "reason": "ok" if invariant and bound and values_ok else "terminal_behavior",
                "row_order_invariant": bool(invariant),
                "deliverable_bound": bool(bound),
                **metrics,
            }
    except Exception as exc:
        payload = {"healthy": False, "reason": f"probe_error:{type(exc).__name__}"}
    print(json.dumps(payload, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
