from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import channels, features

ROOT = Path(__file__).resolve().parent.parent

NOT_RECORDED = [-200, 0]


def build_serving_frame(batch: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    archive = channels.read_log(ROOT / "data" / "history.csv")
    stitched = pd.concat([archive[batch.columns], batch], ignore_index=True)
    stitched = stitched.drop_duplicates("timestamp").sort_values("timestamp", kind="stable")
    for column in channels.CHANNELS:
        stitched[column] = stitched[column].astype(float).replace(NOT_RECORDED, np.nan)

    frame = features.build_features(stitched, window_hours)
    return frame.loc[frame.index.isin(batch["timestamp"])]
