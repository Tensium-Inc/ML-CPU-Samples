"""Turn form-version rows into one entry per funding request.

Every field the deliverable reports comes from one of the rows that carry a
request. Which row is the question this module exists to answer.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent.

    A blank is a different fact from a zero and must stay a blank. Values are
    taken through Decimal so two builds that both read the same text cannot
    disagree in the last place of a binary float.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return str(int((Decimal(text) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    except Exception:
        return ""


def versions(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """funding_request_number -> form_version -> row.

    A request appears once per version of the form that carries it. Original is
    the request as filed; Current is the same request as it stands after
    adjudication. Some requests have only one of the two.
    """
    found: dict[str, dict[str, dict]] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        found.setdefault(frn, {})[row["form_version"]] = row
    return found


def collect(rows: list[dict]) -> dict[str, dict]:
    """funding_request_number -> the row this build reads identity from.

    Identity (the billed entity) does not move between versions. Prefer the
    adjudicated row when it exists so a caller that only has one row still sees
    the request as it stands; fall back to the filed row for requests nobody
    has adjudicated. Money and months are NOT taken from this row alone -- the
    harness reads those from the version each field belongs to.
    """
    chosen: dict[str, dict] = {}
    for frn, vers in versions(rows).items():
        chosen[frn] = vers.get("Current") or vers["Original"]
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
