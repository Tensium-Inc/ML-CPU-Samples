"""Which entity filed a request.

The key this returns is what the deliverable reports, what place-level features
are grouped by, and what the serving cache is keyed on. Two requests that get the
same key are treated as the same applicant by everything downstream, including
anything that holds data out.
"""

from __future__ import annotations


def applicant_key(row: dict) -> str:
    """The applicant key for one row.

    The applicant is the BILLED ENTITY NUMBER (`ben`), never the organisation
    name. Names are not identities: hundreds of names in the extract are shared
    by more than one billed entity, and some entities appear under more than one
    spelling of their own name. The number keys both correctly.
    """
    return row["ben"]
