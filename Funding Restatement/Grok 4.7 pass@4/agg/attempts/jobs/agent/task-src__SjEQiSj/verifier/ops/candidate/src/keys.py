"""Which entity filed a request.

The key this returns is what the deliverable reports, what place-level features
are grouped by, and what the serving cache is keyed on. Two requests that get the
same key are treated as the same applicant by everything downstream, including
anything that holds data out.
"""

from __future__ import annotations


def applicant_key(row: dict) -> str:
    """The billed entity number. Organisation names are not identities."""
    return row["ben"]
