"""Turn form-version rows into one entry per funding request.

The extract records FORM VERSIONS, not requests: a funding request appears once
per version of the form that carries it. Two versions exist --

    Original   the request AS FILED by the applicant, before review.
    Current    the same request AS IT STANDS after adjudication.

Adjudication RESTATES the figures (commitment, pre-discount cost, discount pct
and months all move between versions), so no single row can answer both the
"as filed" questions and the "as committed" question. `collect` therefore keeps
BOTH versions of every request and the caller reads each field off the version
it is defined on.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

FILED = "Original"
ADJUDICATED = "Current"


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent.

    Decimal, not float: two builds that both read `10854.54` correctly must not
    disagree in the last binary place. An empty value stays empty -- nothing to
    report is a different fact from zero.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        value = Decimal(text)
    except InvalidOperation:
        return ""
    return str(int((value * 100).to_integral_value(rounding=ROUND_HALF_UP)))


def collect(rows: list[dict]) -> dict[str, dict]:
    """funding_request_number -> {"filed": row | None, "adjudicated": row | None}.

    One entry per distinct funding request, carrying every version the extract
    has for it. Nothing is chosen here: which version each field of the
    deliverable is read from is decided where the field is written, not by
    throwing one of the versions away.
    """
    chosen: dict[str, dict] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        entry = chosen.setdefault(frn, {"filed": None, "adjudicated": None})
        if row["form_version"] == FILED:
            entry["filed"] = row
        elif row["form_version"] == ADJUDICATED:
            entry["adjudicated"] = row
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
    entries = collect(rows)
    return {
        "rows": len(rows),
        "requests": len(entries),
        "carrying_both_versions": sum(
            1 for e in entries.values() if e["filed"] is not None and e["adjudicated"] is not None
        ),
    }
