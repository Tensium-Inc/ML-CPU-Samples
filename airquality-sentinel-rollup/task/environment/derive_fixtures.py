#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

HIDDEN = Path("/opt/task/hidden")
REQUIRED = ["terminal_batch.csv", "terminal_labels.csv", "sanity_batch.csv", "sanity_labels.csv"]


def main() -> None:
    missing = [n for n in REQUIRED if not (HIDDEN / n).exists() or (HIDDEN / n).stat().st_size == 0]
    if missing:
        sys.exit(f"FATAL: hidden fixtures missing or empty: {missing}")
    print("hidden fixtures present:", ", ".join(sorted(REQUIRED)))


if __name__ == "__main__":
    main()
