#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
SRC = Path(os.environ.get("AIRQUALITY_SOURCE_CSV", HERE / "source" / "AirQualityUCI.csv"))

SENTINEL = -200
SENTINEL_ALT = 0
TARGET = "C6H6(GT)"
ROLL_SOURCE = "PT08.S1(CO)"
SENSORS = ["PT08.S1(CO)", "PT08.S2(NMHC)", "PT08.S3(NOx)", "PT08.S4(NO2)", "PT08.S5(O3)",
           "T", "RH", "AH"]

# Four eras by time: the agent gets the first two, validate and the terminal run on hours it
# has never seen.
# Boundaries chosen so the GRADED era actually contains instrument outages: they cluster in
# time, and the final decile of the corpus is almost clean (0.1%), which would have left the
# defect unable to manifest where it is measured.
HISTORY_FRAC = 0.70         # 2.3% outage hours
DEMO_FRAC = 0.76            # 14.2%
SANITY_FRAC = 0.82          # 9.3%
TERMINAL_FRAC = 0.94        # 7.7%


def load() -> pd.DataFrame:
    df = pd.read_csv(SRC, sep=";", decimal=",", low_memory=False)
    df = df.dropna(axis=1, how="all").dropna(how="all")
    stamp = df["Date"] + " " + df["Time"].str.replace(".", ":", regex=False)
    df.insert(0, "timestamp", pd.to_datetime(stamp, format="%d/%m/%Y %H:%M:%S"))
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    return df.drop(columns=["Date", "Time"])


def reencode_markers(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    chans = [c for c in out.columns if c != "timestamp"]
    ts = pd.to_datetime(out["timestamp"])
    idx = out.index[out[chans].isin([SENTINEL, SENTINEL_ALT]).all(axis=1)]
    if len(idx) == 0:
        return out
    runs = (ts[idx].diff() != pd.Timedelta("1h")).cumsum()
    groups = [list(g) for _, g in runs.groupby(runs).groups.items()]
    if len(groups) == 1:
        g = groups[0]
        groups = [g[: len(g) // 2], g[len(g) // 2:]]
    def assign(pieces):
        marks = {}
        for i, g in enumerate(pieces):
            for r in g:
                marks[r] = SENTINEL if i % 2 == 0 else SENTINEL_ALT
        return marks
    marks = assign(groups)
    alt = sum(1 for m in marks.values() if m == SENTINEL_ALT)
    if min(alt, len(marks) - alt) / len(marks) < 0.3:
        ordered = sorted(groups, key=len, reverse=True)
        big = ordered[0]
        pieces = [big[: len(big) // 2], big[len(big) // 2:]] + ordered[1:]
        marks = assign(pieces)
    for r, mark in marks.items():
        for c in chans:
            if out.at[r, c] in (SENTINEL, SENTINEL_ALT):
                out.at[r, c] = mark
    return out


def write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    reencode_markers(df).to_csv(path, index=False, date_format="%Y-%m-%d %H:%M:%S")
    h = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    print(f"  {path.relative_to(TASK)}  rows={len(df):>6,}  sha256={h}")


def alert_threshold(df: pd.DataFrame) -> float:
    real = df[TARGET].replace([SENTINEL, SENTINEL_ALT], np.nan).dropna()
    return float(round(real.quantile(0.75), 1))


def labels(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    nxt = df[TARGET].replace([SENTINEL, SENTINEL_ALT], np.nan).shift(-1)
    out = pd.DataFrame({"timestamp": df["timestamp"], "label": (nxt > threshold).astype("float")})
    return out.dropna().astype({"label": int})


def main() -> None:
    df = load()
    n = len(df)
    thr = alert_threshold(df)
    h_end, d_end = int(n * HISTORY_FRAC), int(n * DEMO_FRAC)
    s_end, t_end = int(n * SANITY_FRAC), int(n * TERMINAL_FRAC)
    history, demo = df.iloc[:h_end], df.iloc[h_end:d_end]
    sanity, terminal = df.iloc[d_end:s_end], df.iloc[s_end:t_end]
    print(f"source: {n:,} real hours  {df.timestamp.min()} .. {df.timestamp.max()}")
    print(f"alert threshold (75th pct of real {TARGET}): {thr}")

    ship = ["timestamp"] + SENSORS + [TARGET]
    print("\nagent workspace (environment/workspace/data/):")
    write(history[ship], TASK / "environment/workspace/data/history.csv")
    write(demo[ship].drop(columns=[TARGET]), TASK / "environment/workspace/data/current_batch.csv")

    print("\nhidden fixtures (image, root-only /opt/task/hidden/):")
    write(sanity[ship].drop(columns=[TARGET]), TASK / "environment/hidden/sanity_batch.csv")
    write(labels(sanity, thr), TASK / "environment/hidden/sanity_labels.csv")
    write(terminal[ship].drop(columns=[TARGET]), TASK / "environment/hidden/terminal_batch.csv")
    write(labels(terminal, thr), TASK / "environment/hidden/terminal_labels.csv")

    outage = terminal[SENSORS].isin([SENTINEL, SENTINEL_ALT]).any(axis=1)
    print(f"\n  terminal batch: {len(terminal):,} hours, "
          f"{outage.mean():.1%} carry at least one channel reading {SENTINEL}")


if __name__ == "__main__":
    main()
