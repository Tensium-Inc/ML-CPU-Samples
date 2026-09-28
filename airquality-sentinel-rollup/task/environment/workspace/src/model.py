from __future__ import annotations

import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from . import features


def train(X: pd.DataFrame, y: pd.Series, cfg: dict) -> RandomForestClassifier:
    m = cfg.get("model", {})
    clf = RandomForestClassifier(
        n_estimators=int(m.get("n_estimators", 200)),
        min_samples_leaf=int(m.get("min_samples_leaf", 20)),
        random_state=int(m.get("random_state", 0)),
        n_jobs=1,
    )
    clf.fit(X[features.FEATURE_COLUMNS], y)
    return clf


def score(clf: RandomForestClassifier, X: pd.DataFrame) -> pd.Series:
    p = clf.predict_proba(X[features.FEATURE_COLUMNS])[:, 1]
    return pd.Series(p, index=X.index, name="alert_probability")
