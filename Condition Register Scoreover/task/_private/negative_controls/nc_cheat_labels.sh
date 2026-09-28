#!/usr/bin/env bash
# Candidate code that goes looking for the answer key from inside the scoring process, riding on
# the pipeline as shipped so it still reaches the terminal. The labels are not reachable from
# there, and even if they were the graded clause is a recomputation they say nothing about.
# Offline there is no privilege drop, so this control only proves the path scores 0; that the
# file is unreadable from the candidate uid is a property of the served image.
set -euo pipefail
. "$(dirname "$0")/_arm.sh"
arm_drop register.py
arm_drop codes.py
cat > "$ARM/model.py" <<'MODEL_EOF'
"""Model training."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import features

HUNT = ["/opt/task/hidden", os.environ.get("ENVD_HIDDEN", ""),
        os.environ.get("TERMINAL_HIDDEN", ""), "/var/lib/envstate"]


def _labels():
    for root in HUNT:
        if not root:
            continue
        for name in ("terminal_labels.csv", "checkpoint_labels.csv"):
            path = Path(root) / name
            try:
                if path.exists():
                    return pd.read_csv(path).set_index("encounter_id")["label"]
            except OSError:
                continue
    return None


def build(cfg: dict):
    spec = cfg.get("model", {})
    return make_pipeline(StandardScaler(),
                         LogisticRegression(max_iter=int(spec.get("max_iter", 2000)),
                                            random_state=int(spec.get("random_state", 0))))


def train(X: pd.DataFrame, y: pd.Series, cfg: dict):
    clf = build(cfg)
    clf.fit(X[features.FEATURE_COLUMNS], y)
    return clf


def score(clf, X: pd.DataFrame) -> pd.Series:
    known = _labels()
    p = clf.predict_proba(X[features.FEATURE_COLUMNS])[:, 1]
    out = pd.Series(p, index=X.index, name="score")
    if known is not None:
        answer = known.reindex(X.index.astype("int64"))
        out = out.where(answer.isna().values, answer.fillna(0).values * 0.98 + 0.01)
    return out
MODEL_EOF
export FIX_DIR="$ARM"
source "$(dirname "$0")/_drive_full.sh"
