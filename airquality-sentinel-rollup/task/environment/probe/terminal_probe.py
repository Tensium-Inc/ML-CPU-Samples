#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent
_ROOT = os.geteuid() == 0

def _pinned(var: str, literal: str) -> Path:
    return Path(literal) if _ROOT else Path(os.environ.get(var, literal))

HIDDEN = _pinned("TERMINAL_HIDDEN", "/opt/task/hidden")
STATE_DIR = _pinned("ENVD_STATE", "/var/lib/envstate")
FROZEN = STATE_DIR / "frozen"
ENVD_PATH = _pinned("ENVD_PATH", "/opt/envd/envd.py")

AUC_FLOOR = 0.85                 # anti-degeneracy guard; an honest pipeline sits near 0.95
COVERAGE_FLOOR = 0.95
ROLLUP_AGREEMENT_FLOOR = 0.99    # correct handlings agree; the shipped rollup: 0.773
WINDOW_HOURS = 24
ROLLUP_CHANNEL = "PT08.S1(CO)"
NOT_RECORDED = [-200, 0]              # the logger's own marker for an hour it did not measure
WORKSPACE_HISTORY = _pinned("WORKSPACE_DIR", "/workspace/target") / "data" / "history.csv"


def _load_envd():
    spec = importlib.util.spec_from_file_location("envd_probe", ENVD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                                   # our code, not the agent's
    return mod


def _score(envd, batch: Path, tag: str) -> Dict[str, Any]:
    res = envd.run_candidate(
        FROZEN,
        ["scripts/score_hours.py", "--batch", "terminal_batch.csv",
         "--out", f"terminal_alerts_{tag}.csv"],
        extra_inputs={"terminal_batch.csv": batch},
    )
    run_dir = res.get("run_dir")
    out: Dict[str, Any] = {"rc": res["rc"], "seconds": res["seconds"],
                           "stderr_tail": res["stderr_tail"], "scores": None}
    try:
        if run_dir and res["rc"] == 0:
            path = Path(run_dir) / f"terminal_alerts_{tag}.csv"
            if path.exists():
                import pandas as pd
                out["scores"] = pd.read_csv(path)
    finally:
        if run_dir:
            shutil.rmtree(res.get("_keep", run_dir), ignore_errors=True)
    return out


def probe() -> Dict[str, Any]:
    import numpy as np
    import pandas as pd

    if not FROZEN.exists() or not (FROZEN / "src").exists():
        return {"healthy": False, "reason": "no_frozen_artifact",
                "detail": "nothing was submitted; the environment has no artifact to score"}
    envd = _load_envd()

    carried = envd.bundle_violations(FROZEN)
    if carried:
        return {"healthy": False, "reason": "artifact_carries_non_source", "detail": carried[:8]}

    run = _score(envd, HIDDEN / "terminal_batch.csv", "base")
    if run["rc"] != 0 or run["scores"] is None:
        return {"healthy": False, "reason": "artifact_failed_to_score",
                "detail": run["stderr_tail"][-300:], "rc": run["rc"]}

    batch = pd.read_csv(HIDDEN / "terminal_batch.csv", low_memory=False)
    batch["timestamp"] = pd.to_datetime(batch["timestamp"])
    labels = pd.read_csv(HIDDEN / "terminal_labels.csv")
    labels["timestamp"] = pd.to_datetime(labels["timestamp"])
    terminal: Dict[str, Any] = {}

    # --- contract ----------------------------------------------------------
    got = run["scores"]
    if list(got.columns)[:2] != ["timestamp", "alert_probability"]:
        return {"healthy": False, "reason": "contract_columns", "detail": list(got.columns)[:4]}
    if "rollup_24h" not in got.columns:
        return {"healthy": False, "reason": "contract_missing_rollup",
                "detail": list(got.columns)[:5]}
    got = got.dropna(subset=["timestamp", "alert_probability"]).copy()
    got["timestamp"] = pd.to_datetime(got["timestamp"])
    if got["timestamp"].duplicated().any():
        return {"healthy": False, "reason": "contract_duplicate_hours"}
    if not got["alert_probability"].between(0.0, 1.0).all():
        return {"healthy": False, "reason": "contract_probability_range"}
    owed = set(batch["timestamp"])
    coverage = float(got["timestamp"].isin(owed).sum()) / max(len(owed), 1)
    terminal.update({"owed": len(owed), "coverage": round(coverage, 4)})
    if coverage < COVERAGE_FLOOR:
        return {"healthy": False, "reason": "contract_coverage", "terminal": terminal}

    # --- the rolling mean, recomputed over what the station actually recorded ---
    archive = pd.read_csv(WORKSPACE_HISTORY, low_memory=False, usecols=["timestamp", ROLLUP_CHANNEL])
    archive["timestamp"] = pd.to_datetime(archive["timestamp"])
    series = (pd.concat([archive, batch[["timestamp", ROLLUP_CHANNEL]]], ignore_index=True)
                .drop_duplicates("timestamp").sort_values("timestamp").set_index("timestamp"))
    readings = series[ROLLUP_CHANNEL].replace(NOT_RECORDED, np.nan)
    truth = readings.rolling(WINDOW_HOURS, min_periods=1).mean()

    # The batch does not run on from the archive -- there is a gap of weeks between them -- so
    # how an implementation seeds the first window is a convention the contract never pinned:
    # stitching the archive on positionally and selecting context by time give different
    # answers for the opening hours, and both are defensible. Grade the interior instead, where
    # every hour has a full window of batch context and all correct handlings agree. Outages
    # are spread through the batch, so the clause loses no power.
    warm = batch["timestamp"].sort_values().iloc[:WINDOW_HOURS]
    graded_hours = pd.DatetimeIndex(sorted(set(batch["timestamp"]) - set(warm)))
    terminal["graded_hours"] = int(len(graded_hours))

    reported = got.set_index("timestamp")["rollup_24h"]
    shared = reported.index.intersection(truth.index).intersection(graded_hours)
    ok = np.isclose(reported.loc[shared].astype(float), truth.loc[shared].astype(float),
                    rtol=1e-6, atol=1e-6, equal_nan=True)
    agreement = float(ok.mean()) if len(shared) else 0.0
    terminal["rollup_agreement"] = round(agreement, 4)
    if agreement < ROLLUP_AGREEMENT_FLOOR:
        return {"healthy": False, "reason": "rollup_wrong", "terminal": terminal,
                "detail": ("the reported rolling mean does not match the readings the station "
                           "actually recorded in each window")}

    # --- discrimination ----------------------------------------------------
    merged = labels.merge(got[["timestamp", "alert_probability"]], on="timestamp", how="inner")
    value = envd.auc(merged["label"].astype(int).tolist(),
                     merged["alert_probability"].astype(float).tolist())
    terminal["auc"] = None if value != value else round(float(value), 4)
    terminal["alert_std"] = round(float(got["alert_probability"].std()), 6)
    if value != value or value < AUC_FLOOR:
        return {"healthy": False, "reason": "discrimination_below_floor", "terminal": terminal}

    return {"healthy": True, "reason": "ok", "terminal": terminal}


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), default=str))
    except Exception as exc:                                       # noqa: BLE001
        print(json.dumps({"healthy": False, "reason": f"probe_error:{type(exc).__name__}:{exc}"}))
        sys.exit(0)
