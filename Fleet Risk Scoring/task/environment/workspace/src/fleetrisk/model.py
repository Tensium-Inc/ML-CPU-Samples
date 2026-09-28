"""Estimator."""
from __future__ import annotations

from typing import Any, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier


class RiskModel(object):

    def __init__(self, seed, max_iter, learning_rate, max_depth):
        self.seed = int(seed)
        self.max_iter = int(max_iter)
        self.learning_rate = float(learning_rate)
        self.max_depth = int(max_depth)
        self.clf_ = None

    def fit(self, X, y):
        """Values that are not finite are carried as zero."""
        self.clf_ = HistGradientBoostingClassifier(
            max_iter=self.max_iter, learning_rate=self.learning_rate,
            max_depth=self.max_depth, random_state=self.seed,
            early_stopping=False)
        self.clf_.fit(np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0), y)
        return self

    def score(self, X):
        return self.clf_.predict_proba(
            np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0))[:, 1]
