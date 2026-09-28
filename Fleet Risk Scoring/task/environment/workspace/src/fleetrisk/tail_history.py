"""What the fit window knows about the aircraft."""
from __future__ import annotations

import numpy as np
import pandas as pd


def history(fit_flights, groundings, fit_end):
    raise NotImplementedError


def add(df, hist, portfolio):
    raise NotImplementedError
