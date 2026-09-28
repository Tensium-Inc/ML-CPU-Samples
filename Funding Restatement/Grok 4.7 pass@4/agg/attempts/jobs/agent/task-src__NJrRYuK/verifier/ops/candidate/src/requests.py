"""Turn form-version rows into one entry per funding request.

Every field the deliverable reports comes from one of the rows that carry a
request. Which row is the question this module exists to answer, and it is not
the same row for every field.
"""

from __future__ import annotations

from src import labels

AS_FILED = "Original"
AS_ADJUDICATED = "Current"


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent.

    Empty is not zero. A commitment the fund restated as 0 is a real zero; a
    column the extract left blank was never reported.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return str(int(round(float(text) * 100)))
    except ValueError:
        return ""


def versions(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """funding_request_number -> form_version -> row.

    A request appears once per version of the form that carries it. Original is
    the request as filed; Current is the same request as it stands after
    adjudication. Either version may be absent.
    """
    grouped: dict[str, dict[str, dict]] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        grouped.setdefault(frn, {})[row["form_version"]] = row
    return grouped


def collect(rows: list[dict]) -> dict[str, dict]:
    """funding_request_number -> the row identity fields are read from.

    Identity (who filed) does not move between versions. Prefer the adjudicated
    row when it exists so a renamed organisation still resolves to the same
    billed entity; fall back to the filed row for requests nobody has ruled on.
    Money and months are NOT taken from this row blindly — see ``fields``.
    """
    chosen: dict[str, dict] = {}
    for frn, vers in versions(rows).items():
        chosen[frn] = vers.get(AS_ADJUDICATED) or vers[AS_FILED]
    return chosen


def fields(original: dict | None, current: dict | None) -> dict[str, str]:
    """The graded fields of one request, each from the version it belongs to.

    The harness scores whether a request *will be funded*, from what the
    applicant filed. Those figures are the Original version. Reading them off
    Current leaks the decision (a denied request is restated at a zero
    commitment) into the features and makes a hold-out look perfect.

    ``committed_cents`` is the other reading of the same money column: what the
    fund actually granted, which only the adjudicated version records. A
    request with no such version has nothing to report there — empty, not zero.
    """
    filed = original or {}
    granted = current or {}
    return {
        "label": labels.label_from_versions(original, current),
        "applicant_key": (current or original or {})["ben"],
        "committed_cents": cents(granted.get("funding_commitment_request", "")),
        "filed_months": filed.get("months_of_service", ""),
        "filed_commitment_cents": cents(filed.get("funding_commitment_request", "")),
        "filed_pre_discount_cents": cents(filed.get("total_pre_discount_costs", "")),
        "filed_discount_pct": filed.get("dis_pct", ""),
    }


def audit(rows: list[dict]) -> dict[str, int]:
    """This build's own account of the extract, over the rows handed in.

    Called by ``check.release``, which checks it against the extract. It reports
    what THIS build sees, so it is computed from the rows rather than restated
    — an audit that hard-codes an answer is not an audit of anything.

    ``requests`` is how many distinct funding requests these rows carry, and
    ``carrying_both_versions`` how many of them appear as filed AND as
    adjudicated. Both are counted over exactly the rows passed in, so the same
    function has to be right about the whole extract and about a subset of it.
    """
    seen: dict[str, set[str]] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if frn:
            seen.setdefault(frn, set()).add(row["form_version"])
    return {
        "rows": len(rows),
        "requests": len(seen),
        "carrying_both_versions": sum(
            1 for vers in seen.values()
            if AS_FILED in vers and AS_ADJUDICATED in vers
        ),
    }
