"""Turn form-version rows into one entry per funding request.

The extract is a record of FORM VERSIONS: a funding request appears once for
each version of the form that carries it. `Original` is the request AS FILED by
the applicant; `Current` is the same request AS IT STANDS after adjudication.
The two versions do not carry the same numbers -- adjudication restates them --
so no single row can answer every field of the deliverable. `collect` therefore
keeps BOTH versions and the field questions are answered against the version
they belong to (see `harness.build`).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent.

    Decimal arithmetic so that two builds that both read `10854.54` correctly
    cannot disagree in the last binary place of a float. Empty stays empty:
    nothing-to-report and zero are different facts.
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
    """funding_request_number -> {form_version -> row}.

    One entry per distinct funding request, carrying every version of it the
    extract holds. Choosing one version for the whole request was the bug this
    rebuild removes: the deliverable's fields do not all come from the same
    version, so the decision of which version answers which field belongs to
    the caller, per field, not here.
    """
    chosen: dict[str, dict] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        versions = chosen.setdefault(frn, {})
        # at most one row per (request, version) exists; keep the first seen.
        versions.setdefault(row["form_version"], row)
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
