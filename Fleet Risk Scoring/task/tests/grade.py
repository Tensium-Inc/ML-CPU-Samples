#!/usr/bin/env python3
"""Grader for the fleet grounding risk rebuild.

Runs the candidate service in a subprocess against pinned run configs, then compares the
risk scores it produces to the expected values flight by flight. The expected values never
enter the agent's workspace, and the candidate's own configs are replaced with
verifier-side copies so editing a run window cannot change what is graded.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

LOGS = Path(os.environ.get("VERIFIER_LOGS", "/logs/verifier"))
TESTS = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace/target"))

TOLERANCE = 1e-3          # a tenth of a point of probability, not a bit-exact match
AGREE_PASS = 0.999        # a correct rebuild lands inside that band on every row
# Rank quality is reported for diagnosis but does not gate the reward. Measured on this
# build, it cannot discriminate: on the served window a model fitted on rows whose outcome
# the export cannot show scores 0.8495 against gold's 0.8374, so a floor there would pass
# the fault. On the backtest it separates, 0.5875 against 0.4976, but agreement within
# TOLERANCE already implies it. A check that cannot fail is worse than no check.
RUN_TIMEOUT = 2400

# Both windows must agree. The backtest scores ship with the workspace, so credit for
# that window alone would be payable by copying a file that is already there.

REFERENCE_EXPECTED = TESTS / "expected_reference.csv.gz"
CURRENT_EXPECTED = TESTS / "expected_current.csv.gz"


def _outcome(produced_path, expected_path):
    """Rank quality of the produced scores against the labels the export settles.

    Agreement says the numbers match. This says the service still separates the
    flights that were grounded from the ones that were not, which a model fitted on
    rows whose outcome the export cannot show does noticeably worse.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score

    expected = pd.read_csv(expected_path)
    produced = pd.read_csv(produced_path)
    if "label" not in expected.columns:
        return None, "no label column shipped with the expected output"
    merged = expected[["flight_id", "label"]].merge(
        produced[["flight_id", "risk_score"]], on="flight_id", how="inner")
    if merged.empty or merged["label"].nunique() < 2:
        return None, "not enough labelled rows to score by outcome"
    ap = float(average_precision_score(merged["label"], merged["risk_score"]))
    auc = float(roc_auc_score(merged["label"], merged["risk_score"]))
    return None, {"average_precision": round(ap, 6), "roc_auc": round(auc, 6)}


def _stage():
    """Copy the candidate workspace somewhere writable and pin the run configs."""
    staged = Path(tempfile.mkdtemp(prefix="candidate_"))
    shutil.copytree(WORKSPACE, staged / "target", symlinks=False)
    target = staged / "target"
    pinned = TESTS / "pinned"
    if pinned.is_dir():
        (target / "configs").mkdir(parents=True, exist_ok=True)
        for cfg in pinned.glob("*.yaml"):
            shutil.copy(cfg, target / "configs" / cfg.name)
    return target


def _run(target, config_name, out_name):
    out_dir = target / "_grade_out" / out_name
    proc = subprocess.run(
        [sys.executable, "run_scoring.py", "--config", "configs/%s" % config_name,
         "--out", str(out_dir)],
        cwd=str(target), capture_output=True, text=True, timeout=RUN_TIMEOUT,
    )
    produced = out_dir / "scores.csv"
    return proc, (produced if produced.is_file() else None)


def _agreement(produced_path, expected_path):
    """Fraction of expected rows the candidate reproduces within tolerance."""
    expected = pd.read_csv(expected_path)
    produced = pd.read_csv(produced_path)
    for frame, tag in ((expected, "expected"), (produced, "produced")):
        for column in ("flight_id", "risk_score"):
            if column not in frame.columns:
                return 0.0, "%s output has no %s column" % (tag, column)
    if produced["flight_id"].duplicated().any():
        return 0.0, "produced output repeats flight_id"

    merged = expected[["flight_id", "risk_score"]].merge(
        produced[["flight_id", "risk_score"]], on="flight_id", how="left",
        suffixes=("_expected", "_produced"))
    diff = (merged["risk_score_expected"] - merged["risk_score_produced"]).abs()
    matched = (diff <= TOLERANCE).fillna(False)
    note = "%d of %d rows within %g" % (int(matched.sum()), len(merged), TOLERANCE)
    return float(matched.mean()), note


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    detail = {"tolerance": TOLERANCE, "agree_pass": AGREE_PASS}
    reward = 0.0

    try:
        target = _stage()
        for tag, config_name, expected in (
            ("reference", "reference.yaml", REFERENCE_EXPECTED),
            ("current", "current.yaml", CURRENT_EXPECTED),
        ):
            proc, produced = _run(target, config_name, tag)
            if produced is None:
                detail[tag] = {"ran": False,
                               "stderr": (proc.stderr or "")[-800:],
                               "agreement": 0.0}
                continue
            agreement, note = _agreement(produced, expected)
            _, outcome = _outcome(produced, expected)
            detail[tag] = {"ran": True, "agreement": round(agreement, 6), "note": note,
                           "rank_quality": outcome}

        current = detail.get("current", {}).get("agreement", 0.0)
        reference = detail.get("reference", {}).get("agreement", 0.0)
        reward = 1.0 if (current >= AGREE_PASS and reference >= AGREE_PASS) else 0.0
    except Exception as exc:                      # never let the grader crash to 1.0
        detail["error"] = "%s: %s" % (type(exc).__name__, exc)
        reward = 0.0

    detail["reward"] = reward
    LOGS.joinpath("reward.txt").write_text("1" if reward else "0")
    LOGS.joinpath("detail.json").write_text(json.dumps(detail, indent=2, sort_keys=True))
    print(json.dumps(detail, indent=2, sort_keys=True))
    print("Final score: %s" % reward)


if __name__ == "__main__":
    main()
