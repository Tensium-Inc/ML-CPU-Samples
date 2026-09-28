"""Read the pinned extract. No decisions here -- only bytes to rows.

Returns a LIST and not a mapping. There is no column in this file that uniquely
keys a row, and choosing one is a decision that belongs somewhere it can be found
and argued with, not in the loader.
"""

from __future__ import annotations

import csv
import gzip
from pathlib import Path

EXTRACT_NAME = "erate_frn_status_fy2024.csv.gz"


def read_rows(data_root) -> list[dict]:
    """Every row of the extract, in file order, values verbatim."""
    path = Path(data_root) / EXTRACT_NAME
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]
