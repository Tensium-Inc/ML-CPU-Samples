#!/usr/bin/env bash
# No-skill baseline: the register is exactly right, the scores are noise. It drives the whole
# walk correctly and passes the contract, so it can only fail at the discrimination floor --
# which is the point. Without it that floor would be asserted and never measured.
set -euo pipefail
. "$(dirname "$0")/_arm.sh"
cat > "$ARM/model.py" <<'MODEL_EOF'
"""Model training."""
from __future__ import annotations

import hashlib

import pandas as pd

from . import features


class Blind:
    """Ranks encounters by a stable hash of their id. Non-constant, and worth nothing."""

    def fit(self, X, y):
        return self

    def predict_proba(self, X):
        import numpy as np
        out = []
        for key in X.index.astype("int64").tolist():
            digest = hashlib.sha256(str(key).encode()).hexdigest()[:8]
            out.append(int(digest, 16) / 0xFFFFFFFF)
        p = np.clip(np.array(out, dtype=float), 0.001, 0.999)
        return np.column_stack([1.0 - p, p])


def build(cfg: dict):
    return Blind()


def train(X: pd.DataFrame, y: pd.Series, cfg: dict):
    return build(cfg).fit(X[features.FEATURE_COLUMNS], y)


def score(clf, X: pd.DataFrame) -> pd.Series:
    p = clf.predict_proba(X[features.FEATURE_COLUMNS])[:, 1]
    return pd.Series(p, index=X.index, name="score")
MODEL_EOF
export FIX_DIR="$ARM"
source "$(dirname "$0")/_drive_full.sh"
