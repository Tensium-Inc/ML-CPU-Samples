from __future__ import annotations

from pathlib import Path

import pandas as pd

from solution_engine import load_history as _load_workspace_history


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["dteday"] = pd.to_datetime(result["dteday"], errors="raise", format="mixed")
    numeric = [name for name in result.columns if name != "dteday"]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="raise")
    result["instant"] = result["instant"].astype(int)
    return result.sort_values("instant").reset_index(drop=True)


def load_workspace_history(data_dir: str | Path = "data") -> pd.DataFrame:
    return _load_workspace_history(data_dir)


def load_runtime_history(path: str | Path) -> pd.DataFrame:
    return _typed(pd.read_csv(path))


def load_requests(path: str | Path) -> pd.DataFrame:
    return _typed(pd.read_csv(path))
