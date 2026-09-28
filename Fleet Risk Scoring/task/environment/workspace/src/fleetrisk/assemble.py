"""Design matrix assembly."""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from .schema import FEATURES
except ImportError:
    from schema import FEATURES


def matrix(df):
    """The published features, in the declared order, as a float matrix."""
    missing = [name for name in FEATURES if name not in df.columns]
    if missing:
        raise KeyError("design matrix is missing %s" % ", ".join(missing))
    return df[list(FEATURES)].astype("float64").to_numpy()
