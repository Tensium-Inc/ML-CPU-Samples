"""Group form-version rows into requests, and keep both versions of each.

The extract records FORM VERSIONS. A request appears once per version, so the
grouping has to keep both and let the caller say which one each field comes from
-- collapsing to one row here would make that choice invisible.
"""
from __future__ import annotations

AS_FILED = "Original"
AS_ADJUDICATED = "Current"


def cents(raw):
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return str(int(round(float(text) * 100)))
    except ValueError:
        return ""


def collect(rows):
    filed, adjudicated = {}, {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        if row["form_version"] == AS_FILED:
            filed.setdefault(frn, row)
        elif row["form_version"] == AS_ADJUDICATED:
            adjudicated.setdefault(frn, row)
    return {frn: {"filed": filed.get(frn), "adjudicated": adjudicated.get(frn)}
            for frn in set(filed) | set(adjudicated)}


def audit(rows):
    """This build's own account of the extract, over the rows handed in."""
    seen = {}
    for row in rows:
        frn = row["funding_request_number"]
        if frn:
            seen.setdefault(frn, set()).add(row["form_version"])
    return {"rows": len(rows), "requests": len(collect(rows)),
            "carrying_both_versions": sum(1 for v in seen.values() if len(v) > 1)}
