"""Compare a candidate request table to the reference. By value, per field.

Each field is scored SEPARATELY and each carries a tolerance band. That replaces
an all-or-nothing exact match, which graded a build on its worst single request
and made an edge case indistinguishable from not having done the work.

Money is compared as the integer string the deliverable carries, so two builds
that both read `10854.54` correctly cannot disagree in a last binary place --
and a build that reports the ADJUDICATED figure where the filed one belongs is
wrong by a whole number of cents rather than by a rounding step.

The band has to absorb an implementation difference and be far too narrow for an
unanswered question to fit under. Both halves are measured on this corpus:

    band per field                    0.2% of 55,878 =    111 requests

    committed_cents read off the filed row      13,585 requests  122x band
    filed_commitment read off the adjudicated   13,855           125x
    pre-discount read off the adjudicated        8,664            78x
    discount pct read off the adjudicated        3,380            30x
    filed_months read off the adjudicated        1,371            12x
    label read off the filed row                54,605           492x

So the narrowest thing the band must reject clears it twelve times over. A build
that has answered every question passes with room; a build with any one of them
unanswered cannot fit.

`committed_cents` and the `filed_*` fields are read off DIFFERENT versions of the
same request, so a build that has worked out one provenance rule and applied it
everywhere fails exactly one side of the table. That is deliberate: provenance is
a decision per field, not per row.
"""

from __future__ import annotations

from typing import Any

# Per-field agreement required. See the measured margins above.
FIELD_PASS_MIN = 0.998

FIELDS = ("label", "applicant_key", "committed_cents", "filed_months",
          "filed_commitment_cents", "filed_pre_discount_cents",
          "filed_discount_pct")


def compare(candidate: dict[str, dict], reference: dict[str, dict]) -> dict[str, Any]:
    missing = sorted(set(reference) - set(candidate))
    surplus = sorted(set(candidate) - set(reference))
    shared = set(reference) & set(candidate)
    total = len(reference)

    per_field = {f: sum(1 for r in shared if candidate[r].get(f) == reference[r][f])
                 for f in FIELDS}
    rates = {f: (per_field[f] / total) if total else 0.0 for f in FIELDS}
    whole = sum(1 for r in shared
                if all(candidate[r].get(f) == reference[r][f] for f in FIELDS))
    labels_cand: dict[Any, int] = {}
    for r in shared:
        key = candidate[r].get("label")
        labels_cand[key] = labels_cand.get(key, 0) + 1
    wrong = sorted(r for r in shared
                   if any(candidate[r].get(f) != reference[r][f] for f in FIELDS))
    return {
        "row_pass_rate": (whole / total) if total else 0.0,
        "requests_reference": total,
        "requests_agreeing": whole,
        "requests_missing": len(missing),
        "requests_surplus": len(surplus),
        "field_pass_min": FIELD_PASS_MIN,
        **{f + "_agreeing": per_field[f] for f in FIELDS},
        **{f + "_rate": round(rates[f], 6) for f in FIELDS},
        "fields_passing": sorted(f for f in FIELDS if rates[f] >= FIELD_PASS_MIN),
        "fields_failing": sorted(f for f in FIELDS if rates[f] < FIELD_PASS_MIN),
        "candidate_label_counts": labels_cand,
        "sample_wrong": wrong[:5],
    }


def is_clean(result: dict[str, Any]) -> bool:
    """Every question answered inside its band, over exactly the right requests."""
    return (not result["fields_failing"]
            and result["requests_missing"] == 0
            and result["requests_surplus"] == 0)
