#!/usr/bin/env bash
# POSITIVE control despite the nc_ prefix: the gold fix with its probabilities post-processed to
# percentile ranks, and the register field written in an arbitrary order rather than sorted. The
# contract asks for a score in [0,1] and for the conditions on file; it says nothing about
# calibration or about the order a set is written down in. Must still score exactly 1.0 --
# this is what proves the terminal grades a value and not a byte-identical clone of gold.
set -euo pipefail
. "$(dirname "$0")/_arm.sh"
cat > "$ARM/serve.py" <<'SERVE_EOF'
"""Turning a scored batch into the export the network receives."""
from __future__ import annotations

import pandas as pd

from . import features, register


def build_serving_frame(batch: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    return features.build_features(batch, cfg)


def scored_rows(batch: pd.DataFrame, scores: pd.Series, cfg: dict) -> pd.DataFrame:
    """One row per encounter: a percentile rank, and the register in hash order."""
    columns = list(cfg["scoring"]["output_columns"])
    separator = cfg["register"]["separator"]
    reg = register.registers(batch, cfg)
    joined = reg.groupby("encounter_id")["code"].agg(
        lambda s: separator.join(sorted(set(s), key=lambda c: (len(c), c[::-1]))))
    ranked = scores.astype(float).rank(pct=True, method="average")
    out = pd.DataFrame({"encounter_id": scores.index.astype("int64"),
                        "score": ranked.values})
    out["conditions"] = out["encounter_id"].map(joined).fillna("")
    return out.sort_values("encounter_id", kind="stable")[columns].reset_index(drop=True)
SERVE_EOF
export FIX_DIR="$ARM"
source "$(dirname "$0")/_drive_full.sh"
