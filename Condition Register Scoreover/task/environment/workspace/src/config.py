"""Reading the pipeline policy.

The service that builds a release refuses to certify one whose shipped policy is missing a key
the contract depends on, so the keys listed here are read back rather than defaulted.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_KEYS = [
    ("register", "code_columns"),
    ("register", "separator"),
    ("scoring", "output_columns"),
    ("paths", "encounters"),
]


def load(path: str | Path | None = None) -> Dict[str, Any]:
    """The pipeline policy, as a dict."""
    path = Path(path) if path else ROOT / "config.yaml"
    return yaml.safe_load(path.read_text()) or {}


def missing_keys(cfg: Dict[str, Any]) -> list[str]:
    """Required policy keys that are absent from `cfg`, as dotted names."""
    absent = []
    for section, key in REQUIRED_KEYS:
        if key not in (cfg.get(section) or {}):
            absent.append(f"{section}.{key}")
    return absent


def require(cfg: Dict[str, Any]) -> Dict[str, Any]:
    absent = missing_keys(cfg)
    if absent:
        raise KeyError(f"policy is missing required keys: {', '.join(absent)}")
    return cfg
