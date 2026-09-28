from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import channels, features

ROOT = Path(__file__).resolve().parent.parent

# The cabinet used to be powered down overnight, so nothing was published outside these hours.
PUBLISHING_HOURS = range(6, 22)


def build_serving_frame(batch: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    archive = channels.read_log(ROOT / "data" / "history.csv")
    stitched = pd.concat([archive[batch.columns], batch], ignore_index=True)
    stitched = stitched.sort_values("timestamp", kind="stable")

    frame = features.build_features(stitched, window_hours)
    frame = frame.loc[frame.index.isin(batch["timestamp"])]
    return frame.loc[frame.index.hour.isin(PUBLISHING_HOURS)]
