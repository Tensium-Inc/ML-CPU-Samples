from __future__ import annotations

import pandas as pd

SENSORS = ["PT08.S1(CO)", "PT08.S2(NMHC)", "PT08.S3(NOx)", "PT08.S4(NO2)", "PT08.S5(O3)"]
WEATHER = ["T", "RH", "AH"]
CHANNELS = SENSORS + WEATHER

# The channel the operator display rolls up.
ROLLUP_CHANNEL = "PT08.S1(CO)"


def read_log(path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
