"""Turn form-version rows into one entry per funding request.

Every field the deliverable reports comes from one of the rows that carry a
request. Which row is the question this module exists to answer.
"""

from __future__ import annotations

from collections import defaultdict


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent."""
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return str(int(round(float(text) * 100)))
    except ValueError:
        return ""


def versions_of(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """funding_request_number -> form_version -> row."""
    grouped: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        frn = row["funding_request_number"]
        if frn:
            grouped[frn][row["form_version"]] = row
    return grouped


def collect(rows: list[dict]) -> dict[str, dict]:
    """funding_request_number -> a representative row.

    Kept so audit() can count distinct requests. Field values are read from a
    specific version in the harness, not from this row.
    """
    chosen: dict[str, dict] = {}
    for frn, versions in versions_of(rows).items():
        chosen[frn] = versions.get("Current") or versions.get("Original")
    return chosen


def audit(rows: list[dict]) -> dict[str, int]:
    """This build's own account of the extract, over the rows handed in.

    `requests` is how many distinct funding requests these rows carry, and
    `carrying_both_versions` how many of them appear as filed AND as adjudicated.
    Both are counted over exactly the rows passed in.
    """
    seen: dict[str, set[str]] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if frn:
            seen.setdefault(frn, set()).add(row["form_version"])
    return {
        "rows": len(rows),
        "requests": len(seen),
        "carrying_both_versions": sum(1 for v in seen.values() if len(v) > 1),
    }
