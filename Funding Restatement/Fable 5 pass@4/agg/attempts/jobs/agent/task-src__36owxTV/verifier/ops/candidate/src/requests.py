"""Turn form-version rows into one entry per funding request.

The extract is a record of FORM VERSIONS, not of funding requests: a request
appears once for each version of the form that carries it. Two versions exist,

  Original   the request AS FILED by the applicant, before review.
  Current    the same request AS IT STANDS after adjudication.

The two versions DO NOT carry the same numbers -- adjudication restates them --
so no single row can answer every field of the deliverable. `collect` therefore
keeps BOTH versions of every request and the caller reads each field off the
version that carries the fact it is reporting: the filed figures off the
Original version, the committed figure off the Current one.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ORIGINAL = "Original"
CURRENT = "Current"


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent.

    Exact decimal arithmetic: two builds that both read `10854.54` correctly
    cannot disagree in the last binary place of a float.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        value = Decimal(text)
    except InvalidOperation:
        return ""
    return str(int((value * 100).to_integral_value(rounding=ROUND_HALF_UP)))


def collect(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """funding_request_number -> {form_version: row}.

    One entry per distinct funding request, carrying every version of the form
    the rows hand in. The extract carries at most one row per (request, version);
    if a subset ever repeated one, the first occurrence wins.
    """
    versions: dict[str, dict[str, dict]] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        versions.setdefault(frn, {}).setdefault(row["form_version"], row)
    return versions


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
    versions = collect(rows)
    return {
        "rows": len(rows),
        "requests": len(versions),
        "carrying_both_versions": sum(
            1 for v in versions.values() if ORIGINAL in v and CURRENT in v),
    }
