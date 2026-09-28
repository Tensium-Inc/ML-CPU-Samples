"""Turn form-version rows into one entry per funding request.

Every field the deliverable reports comes from one of the rows that carry a
request. Which row is the question this module exists to answer, and the
answer is not the same row for every field.
"""

from __future__ import annotations

from src.labels import label_from_versions


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent.

    A blank is nothing to report. A zero is a zero. Those are different facts,
    so a missing value is never written as 0.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return str(int(round(float(text) * 100)))
    except ValueError:
        return ""


def versions_of(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """funding_request_number -> form_version -> row.

    A request appears once per version of the form that carries it. Keeping
    both is the whole point: the as-filed numbers and the as-committed numbers
    live on different versions and are not the same figure.
    """
    grouped: dict[str, dict[str, dict]] = {}
    for row in rows:
        frn = row.get("funding_request_number", "")
        if not frn:
            continue
        grouped.setdefault(frn, {})[row.get("form_version", "")] = row
    return grouped


def collect(rows: list[dict]) -> dict[str, dict]:
    """funding_request_number -> the row a single-version reader would use.

    Retained so a caller that still wants one row gets the adjudicated version
    when there is one (it is the version a decision can be read from) and the
    as-filed version otherwise. The deliverable does not read every field from
    this row — see `record`.
    """
    chosen: dict[str, dict] = {}
    for frn, versions in versions_of(rows).items():
        chosen[frn] = versions.get("Current") or versions.get("Original") or next(iter(versions.values()))
    return chosen


def record(versions: dict[str, dict]) -> dict:
    """One deliverable row, each field read from the version it belongs to.

    `committed_cents` is what the fund granted, which only exists on the
    adjudicated version. The filed figures are what the applicant asked for,
    which only exists on the as-filed version. A request that has only one of
    those versions reports the other side as empty rather than borrowing the
    number from the version it does have — they are not the same fact.
    """
    # The harness exists to score a request from what was asked for, before
    # anyone ruled. Those figures live on Original and only there: a request
    # that was never captured as filed has nothing filed to report, and a blank
    # as-filed cell stays blank rather than being filled from the version
    # adjudication restated. The commitment is what the fund granted, which is
    # the same column on Current and is empty when nobody has adjudicated.
    filed = versions.get("Original")
    committed = versions.get("Current")
    identity = filed or committed or {}
    return {
        "label": label_from_versions(versions),
        "applicant_key": identity.get("ben", ""),
        "committed_cents": cents(committed.get("funding_commitment_request", "")) if committed else "",
        "filed_months": filed.get("months_of_service", "") if filed else "",
        "filed_commitment_cents": cents(filed.get("funding_commitment_request", "")) if filed else "",
        "filed_pre_discount_cents": cents(filed.get("total_pre_discount_costs", "")) if filed else "",
        "filed_discount_pct": filed.get("dis_pct", "") if filed else "",
    }


def build_table(rows: list[dict]) -> dict[str, dict]:
    """The deliverable, keyed by funding request number. One entry each."""
    return {frn: record(versions) for frn, versions in versions_of(rows).items()}


def audit(rows: list[dict]) -> dict[str, int]:
    """This build's own account of the extract, over the rows handed in.

    Called by `check.release`, which checks it against the extract. It reports
    what THIS build sees, so it is computed from the rows rather than restated
    — an audit that hard-codes an answer is not an audit of anything.

    `requests` is how many distinct funding requests these rows carry, and
    `carrying_both_versions` how many of them appear as filed AND as adjudicated.
    Both are counted over exactly the rows passed in, so the same function has to
    be right about the whole extract and about a subset of it.
    """
    seen: dict[str, set[str]] = {}
    for row in rows:
        frn = row.get("funding_request_number", "")
        if frn:
            seen.setdefault(frn, set()).add(row.get("form_version", ""))
    return {
        "rows": len(rows),
        "requests": len(seen),
        "carrying_both_versions": sum(1 for v in seen.values() if len(v) > 1),
    }
