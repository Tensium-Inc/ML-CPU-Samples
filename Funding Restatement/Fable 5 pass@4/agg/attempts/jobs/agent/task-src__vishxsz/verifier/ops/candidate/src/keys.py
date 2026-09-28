"""Which entity filed a request.

The key this returns is what the deliverable reports, what place-level features
are grouped by, and what the serving cache is keyed on. Two requests that get the
same key are treated as the same applicant by everything downstream, including
anything that holds data out.
"""

from __future__ import annotations


def applicant_key(row: dict) -> str:
    """The applicant key for one row: the BILLED ENTITY NUMBER.

    Names are not identities. Hundreds of organisation names in this extract are
    shared by more than one billed entity (so a name-keyed table runs different
    applicants together), and some entities appear under more than one spelling
    of their own name (so a name-keyed table splits one applicant apart). The
    number does neither. It is identical on every version of every request.
    """
    return row["ben"]
