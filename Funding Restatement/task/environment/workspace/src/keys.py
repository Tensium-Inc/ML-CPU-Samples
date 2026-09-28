"""Which entity filed a request.

The key this returns is what the deliverable reports, what place-level features
are grouped by, and what the serving cache is keyed on. Two requests that get the
same key are treated as the same applicant by everything downstream, including
anything that holds data out.
"""

from __future__ import annotations


def applicant_key(row: dict) -> str:
    """The applicant key for one row.

    TODO(desk): this is the organisation name. The desk has raised twice that
    names are not unique; the `applicant` ops note specifies what the key is
    supposed to be.
    """
    return row["organization_name"]
