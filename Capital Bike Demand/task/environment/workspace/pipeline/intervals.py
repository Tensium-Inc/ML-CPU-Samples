from __future__ import annotations

import numpy as np


def interval_radius(absolute_residuals) -> float:
    values = np.asarray(absolute_residuals, dtype=float)
    return float(np.quantile(values, 0.20))


def bounds(prediction, radius: float):
    point = np.asarray(prediction, dtype=float)
    return np.maximum(point - radius, 0.0), point + radius
