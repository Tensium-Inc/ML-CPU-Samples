"""The outcome of a request, read off the adjudicated version.

A cancelled request IS decided: the extract stamps `pending_reason = FCDL Issued`
on it exactly as it does on a funded or denied one, which is the decision letter
going out, and its adjudicated commitment is 0.00 like every denial. It is an
adverse outcome, not a withdrawal before review.
"""
from __future__ import annotations

DECIDED = {"QK7", "VR9", "ZP2", "VD4"}
FUNDED = {"QK7", "VR9"}

def _committed(row):
    try:
        return float((row.get("funding_commitment_request") or "").strip())
    except ValueError:
        return None


def _carried(row):
    return bool((row.get("wave_sequence_number") or "").strip())


def _really_funded(row):
    """Approved on paper is not funded. The fund has to have committed money
    and a wave has to have carried it -- the oracle splits 631 requests that
    say Funded and were not."""
    return _committed(row) not in (None, 0.0) and _carried(row)




def label(adjudicated):
    if adjudicated is None or adjudicated.get("form_471_frn_status_name") not in DECIDED:
        return "undecided"
    if adjudicated["form_471_frn_status_name"] not in FUNDED:
        return "not_funded"
    return "funded" if _really_funded(adjudicated) else "not_funded"
