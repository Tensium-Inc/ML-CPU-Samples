"""The diagnosis codes recorded on an encounter."""
from __future__ import annotations

import pandas as pd

BLANKS = ("", "nan", "None")


def normalise(raw: pd.Series, missing: str = "?") -> pd.Series:
    """Recorded diagnosis codes, tidied for use as register entries.

    The missing marker and blank cells come back as NaN so they never reach a register.
    Everything else is kept as charted, which is what the code table is keyed on.
    """
    text = raw.astype(str).str.strip()
    return text.where(~text.isin((missing, *BLANKS)))
