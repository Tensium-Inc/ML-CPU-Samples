"""Labelling, and the subset of the export the desk fits on."""
from __future__ import annotations

import numpy as np
import pandas as pd


def attach_label(flights, groundings, window_days):
    raise NotImplementedError


def observed(df, fit_spec, export_end, window_days):
    raise NotImplementedError
