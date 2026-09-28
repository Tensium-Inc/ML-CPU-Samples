"""Which entity filed a request.

The key this returns is what the deliverable reports, what place-level features
are grouped by, and what the serving cache is keyed on. Two requests that get the
same key are treated as the same applicant by everything downstream, including
anything that holds data out.
"""

from __future__ import annotations


def applicant_key(row: dict) -> str:
    """The billed entity number, never the organisation name.

    Names are not identities: the same spelling is used by more than one billed
    entity, and one billed entity appears under more than one spelling. The
    number is what keeps one applicant together and two applicants apart.
    """
    return row["ben"]
