"""Turn form-version rows into one entry per funding request.

The extract is not one row per funding request: it records FORM VERSIONS, and a
request appears once per version of the form that carries it. Two versions
exist -- `Original`, the request AS FILED by the applicant before review, and
`Current`, the same request AS IT STANDS after adjudication. The two versions
do not carry the same numbers: adjudication restates them.

So there is no single "row this build reads its fields from". Each field of the
deliverable names the version it is read off: the filed_* fields are read off
the Original version, and the committed figure off the Current one. `collect`
therefore keeps BOTH versions of every request and the caller reads each field
from the version that carries the fact it is reporting. A version the extract
does not carry is absent from the mapping, and the fields that would have been
read off it have nothing to report.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

FILED = "Original"
ADJUDICATED = "Current"


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent.

    Exact decimal arithmetic, so that two builds that both read `10854.54`
    correctly cannot disagree in the last binary place of a float. An empty
    column is an empty string, never a zero -- those are different facts.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        value = Decimal(text) * 100
    except InvalidOperation:
        return ""
    return str(int(value.to_integral_value()))


def collect(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """funding_request_number -> {form_version -> row}.

    Every distinct funding request in `rows`, carrying whichever of its form
    versions the extract has. The first row seen wins for a duplicated
    (request, version) pair, which the pinned extract does not contain.
    """
    chosen: dict[str, dict[str, dict]] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        versions = chosen.setdefault(frn, {})
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
    collected = collect(rows)
    return {
        "rows": len(rows),
        "requests": len(collected),
        "carrying_both_versions": sum(1 for v in collected.values() if len(v) > 1),
    }
