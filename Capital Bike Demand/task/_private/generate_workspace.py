#!/usr/bin/env python3
"""Regenerate the deterministic real-data surfaces for the Capital Bike task."""
from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
from pathlib import Path


TASK = Path(__file__).resolve().parents[1]
SOURCE = TASK / "_private" / "source" / "hour.csv"
WORKSPACE_DATA = TASK / "environment" / "workspace" / "data"
PRIVATE = TASK / "environment" / "backend" / "private"
TERMINAL = TASK / "tests" / "terminal.csv"
SOURCE_SHA256 = "e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f"
CANONICAL = [
    "instant", "dteday", "season", "yr", "mnth", "hr", "holiday",
    "weekday", "workingday", "weathersit", "temp", "atemp", "hum",
    "windspeed", "casual", "registered", "cnt",
]


def read_source() -> list[dict[str, str]]:
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise SystemExit("source checksum mismatch")
    with SOURCE.open(encoding="ascii", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 17_379 or list(rows[0]) != CANONICAL:
        raise SystemExit("unexpected UCI source contract")
    return rows


def write_csv(
    path: Path,
    rows: list[dict[str, str]],
    fields: list[str],
    delimiter: str = ",",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def transform(
    rows: list[dict[str, str]],
    aliases: dict[str, str],
    scales: dict[str, float] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    scales = scales or {}
    fields = [aliases.get(name, name) for name in CANONICAL]
    result = []
    for source in rows:
        target = {}
        for name in CANONICAL:
            renamed = aliases.get(name, name)
            value = source[name]
            if renamed in scales:
                value = f"{float(value) * scales[renamed]:.6f}".rstrip("0").rstrip(".")
            target[renamed] = value
        result.append(target)
    return result, fields


def main() -> int:
    rows = read_source()
    history_dir = WORKSPACE_DATA / "history"
    if history_dir.exists():
        shutil.rmtree(history_dir)
    history_dir.mkdir(parents=True)

    first = [row for row in rows if row["dteday"] < "2011-07-01"]
    second = [row for row in rows if "2011-07-01" <= row["dteday"] < "2012-01-01"]
    third = [row for row in rows if "2012-01-01" <= row["dteday"] < "2012-03-01"]
    fourth = [row for row in rows if "2012-03-01" <= row["dteday"] < "2012-05-01"]
    wave1 = [row for row in rows if "2012-05-01" <= row["dteday"] < "2012-07-01"]
    wave2 = [row for row in rows if "2012-07-01" <= row["dteday"] < "2012-09-01"]
    terminal = [row for row in rows if row["dteday"] >= "2012-09-01"]

    write_csv(history_dir / "2011_h1.csv", first, CANONICAL)
    aliases2 = {
        "instant": "row_id", "dteday": "date", "season": "season_code",
        "yr": "year_index", "mnth": "month", "hr": "hour",
        "holiday": "is_holiday", "weekday": "weekday_index",
        "workingday": "is_working_day", "weathersit": "weather_code",
        "temp": "temperature_norm", "atemp": "feels_like_norm",
        "hum": "humidity_norm", "windspeed": "wind_norm",
        "casual": "casual_count", "registered": "member_count", "cnt": "demand",
    }
    changed2, fields2 = transform(second, aliases2)
    write_csv(history_dir / "2011_h2_semicolon.csv", changed2, fields2, ";")
    aliases3 = {
        "temp": "temp_pct", "atemp": "atemp_pct", "hum": "hum_pct",
        "windspeed": "windspeed_pct", "cnt": "total_count",
    }
    changed3, fields3 = transform(
        third,
        aliases3,
        {"temp_pct": 100.0, "atemp_pct": 100.0, "hum_pct": 100.0, "windspeed_pct": 100.0},
    )
    write_csv(history_dir / "2012_jan_feb_pipe.csv", changed3, fields3, "|")
    noisy = [dict(row) for row in fourth] + [dict(row) for row in fourth[::19][:72]]
    random.Random(20260826).shuffle(noisy)
    write_csv(history_dir / "2012_mar_apr_duplicates.csv", noisy, CANONICAL)

    registry = {
        "canonical_columns": CANONICAL,
        "expected_unique_history_rows": 11_539,
        "history_start": "2011-01-01",
        "history_end": "2012-04-30",
        "exports": [
            {"file": "history/2011_h1.csv", "delimiter": ",", "expected_raw_rows": len(first), "expected_unique_rows": len(first), "rename": {}, "scale_to_canonical": {}},
            {"file": "history/2011_h2_semicolon.csv", "delimiter": ";", "expected_raw_rows": len(second), "expected_unique_rows": len(second), "rename": {value: key for key, value in aliases2.items()}, "scale_to_canonical": {}},
            {"file": "history/2012_jan_feb_pipe.csv", "delimiter": "|", "expected_raw_rows": len(third), "expected_unique_rows": len(third), "rename": {value: key for key, value in aliases3.items()}, "scale_to_canonical": {"temp": 0.01, "atemp": 0.01, "hum": 0.01, "windspeed": 0.01}},
            {"file": "history/2012_mar_apr_duplicates.csv", "delimiter": ",", "expected_raw_rows": len(noisy), "expected_unique_rows": len(fourth), "rename": {}, "scale_to_canonical": {}, "deduplicate_on": "instant"},
        ],
    }
    (WORKSPACE_DATA / "schema_registry.json").write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )

    request_fields = CANONICAL[:-3]
    requests = [{name: row[name] for name in request_fields} for row in terminal]
    random.Random(9102026).shuffle(requests)
    write_csv(WORKSPACE_DATA / "forecast.csv", requests, request_fields)
    write_csv(PRIVATE / "base_history.csv", first + second + third + fourth, CANONICAL)
    write_csv(PRIVATE / "validation_wave1.csv", wave1, CANONICAL)
    write_csv(PRIVATE / "validation_wave2.csv", wave2, CANONICAL)
    write_csv(PRIVATE / "terminal_requests.csv", requests, request_fields)
    write_csv(TERMINAL, terminal, CANONICAL)
    print("generated deterministic Capital Bike data surfaces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
