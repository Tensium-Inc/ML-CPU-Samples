from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


CANONICAL_COLUMNS = [
    "instant",
    "dteday",
    "season",
    "yr",
    "mnth",
    "hr",
    "holiday",
    "weekday",
    "workingday",
    "weathersit",
    "temp",
    "atemp",
    "hum",
    "windspeed",
    "casual",
    "registered",
    "cnt",
]


def _types(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["dteday"] = pd.to_datetime(result["dteday"], errors="raise", format="mixed")
    numeric = [name for name in result.columns if name != "dteday"]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="raise")
    return result


def load_workspace_history(data_dir: str | Path = "data") -> pd.DataFrame:
    root = Path(data_dir)
    registry = json.loads((root / "schema_registry.json").read_text(encoding="ascii"))
    parts = []
    for spec in registry["exports"]:
        part = pd.read_csv(root / spec["file"], sep=spec["delimiter"])
        part = part.rename(columns=spec.get("rename", {}))
        parts.append(part.reindex(columns=CANONICAL_COLUMNS))
    return _types(pd.concat(parts, ignore_index=True)).sort_values("instant").reset_index(drop=True)


def load_runtime_history(path: str | Path) -> pd.DataFrame:
    return _types(pd.read_csv(path)).sort_values("instant").reset_index(drop=True)


def load_requests(path: str | Path) -> pd.DataFrame:
    return _types(pd.read_csv(path)).sort_values("instant").reset_index(drop=True)
