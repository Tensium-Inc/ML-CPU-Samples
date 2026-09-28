"""Model training. Deterministic: the pipeline is replayed and compared run to run."""
from __future__ import annotations

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import features


def build(cfg: dict):
    spec = cfg.get("model", {})
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=int(spec.get("max_iter", 2000)),
                           random_state=int(spec.get("random_state", 0))),
    )


def train(X: pd.DataFrame, y: pd.Series, cfg: dict):
    clf = build(cfg)
    clf.fit(X[features.FEATURE_COLUMNS], y)
    return clf


def score(clf, X: pd.DataFrame) -> pd.Series:
    p = clf.predict_proba(X[features.FEATURE_COLUMNS])[:, 1]
    return pd.Series(p, index=X.index, name="score")
