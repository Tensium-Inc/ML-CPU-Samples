"""Turn form-version rows into one entry per funding request.

Every field the deliverable reports comes from one of the rows that carry a
request. Which row is the question this module exists to answer.
"""

from __future__ import annotations


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent."""
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return str(int(round(float(text) * 100)))
    except ValueError:
        return ""


def collect(rows: list[dict]) -> dict[str, dict]:
    """funding_request_number -> the row this build reads its fields from.

    TODO(desk): this takes the most recently processed version of each request --
    the one carrying a funding wave -- on the reasoning that the latest version is
    the most accurate. Nobody has checked whether the two versions carry the same
    numbers, or whether "most accurate" is the same thing as "what the applicant
    asked for". See the `requests` ops note, which says what each field of the
    deliverable is supposed to be read from.
    """
    chosen: dict[str, dict] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        current = chosen.get(frn)
        if current is None or (row["wave_sequence_number"] and not current["wave_sequence_number"]):
            chosen[frn] = row
    return chosen


def audit(rows: list[dict]) -> dict[str, int]:
    """This build's own account of the extract, over the rows handed in.

    Called by `check.release`, which checks it against the extract. It reports
    what THIS build sees, so it is computed from `collect` rather than restated --
    an audit that hard-codes an answer is not an audit of anything.

    `requests` is how many distinct funding requests these rows carry, and
    `carrying_both_versions` how many of them appear as filed AND as adjudicated.
    Both are counted over exactly the rows passed in, so the same function has to
    be right about the whole extract and about a subset of it.
    """
    seen: dict[str, set[str]] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if frn:
            seen.setdefault(frn, set()).add(row["form_version"])
    return {
        "rows": len(rows),
        "requests": len(collect(rows)),
        "carrying_both_versions": sum(1 for v in seen.values() if len(v) > 1),
    }
