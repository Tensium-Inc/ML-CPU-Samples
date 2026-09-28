"""Run summary written beside the scores."""
from __future__ import annotations

import json
from pathlib import Path


def summarise(scores, cfg):
    return {
        "fit_window": dict(cfg["windows"]["fit"]),
        "score_window": dict(cfg["windows"]["score"]),
        "rows_scored": int(len(scores)),
        "watch_rate": round(float(scores["watch"].mean()), 6),
        "mean_score": round(float(scores["risk_score"].mean()), 6),
    }


def write(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
