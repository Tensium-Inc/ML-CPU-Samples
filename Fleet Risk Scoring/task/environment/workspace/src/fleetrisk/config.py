"""Run configuration."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parents[1]

DEFAULTS: Dict[str, Any] = {
    "paths": {"data_dir": "data"},
    "labelling": {"window_days": 3},
    "encoding": {"smoothing": 50.0},
    "recent": {"flights": 20},
    "model": {"seed": 5, "max_iter": 200, "learning_rate": 0.08, "max_depth": 6},
    "scoring": {"watch_threshold": 0.25},
}


class ConfigError(RuntimeError):
    """Raised when the run configuration cannot be used as written."""


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(path: str) -> Dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    cfg = _merge(DEFAULTS, raw)
    for section in ("windows",):
        if section not in cfg:
            raise ConfigError("config is missing the %s section" % section)
    return cfg


def data_path(name: str, cfg: Dict[str, Any] | None = None) -> Path:
    base = Path((cfg or DEFAULTS)["paths"]["data_dir"])
    return base / name
