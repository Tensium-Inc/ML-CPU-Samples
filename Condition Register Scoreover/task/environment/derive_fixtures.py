#!/usr/bin/env python3
"""Derive the archive copies the terminal probe needs, at image build time.

A COPY'd script rather than a heredoc RUN: a heredoc needs BuildKit and silently does nothing
under the classic builder, which passes every local check and then scores gold 0 on a fresh
clone. Every fixture is asserted present and non-empty before this exits.

`archive_full.csv` is the copy the terminal stages over `data/encounters.csv` on every scored
run, so the frozen release reads the same history the verifier recomputes against.
`archive_trimmed.csv` is the same archive cut short, sliced on raw lines so nothing is re-quoted
on the way through.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# The image sets neither variable, so the pinned container paths are what run at build time.
# Offline calibration points them at the task tree to derive the same two files locally.
WORKSPACE = Path(os.environ.get("DERIVE_WORKSPACE", "/workspace/target"))
HIDDEN = Path(os.environ.get("DERIVE_HIDDEN", "/opt/task/hidden"))

SHIPPED = ["checkpoint_batch.csv", "checkpoint_labels.csv", "canary_batch.csv",
           "terminal_batch.csv", "terminal_labels.csv"]
DERIVED = ["archive_full.csv", "archive_trimmed.csv"]
TRIM_FRACTION = 0.5


def main() -> None:
    source = WORKSPACE / "data" / "encounters.csv"
    if not source.exists():
        sys.exit(f"FATAL: the encounter archive is not where it was expected: {source}")

    HIDDEN.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, HIDDEN / "archive_full.csv")

    with source.open("rb") as fh:
        lines = fh.readlines()
    if len(lines) < 2:
        sys.exit("FATAL: the encounter archive is empty")
    header, body = lines[0], lines[1:]
    keep = body[: int(len(body) * TRIM_FRACTION)]
    with (HIDDEN / "archive_trimmed.csv").open("wb") as fh:
        fh.write(header)
        fh.writelines(keep)

    missing = [name for name in SHIPPED + DERIVED
               if not (HIDDEN / name).exists() or (HIDDEN / name).stat().st_size == 0]
    if missing:
        sys.exit(f"FATAL: hidden fixtures missing or empty: {missing}")
    print(f"hidden fixtures ready: {len(SHIPPED)} shipped, archive_full={len(body)} rows, "
          f"archive_trimmed={len(keep)} rows")


if __name__ == "__main__":
    main()
