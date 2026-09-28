"""Which entity filed a request.

The key this returns is what the deliverable reports, what place-level features
are grouped by, and what the serving cache is keyed on. Two requests that get the
same key are treated as the same applicant by everything downstream, including
anything that holds data out.
"""

from __future__ import annotations

from . import requests


def applicant_key(versions: dict[str, dict]) -> str:
    """The applicant key for one request: the BILLED ENTITY NUMBER.

    Names are not identities: 600 organisation names in this extract are used by
    more than one billed entity, and 29 billed entities appear under more than
    one spelling of their own name. The number never differs between the two
    versions of a request; the name sometimes does.
    """
    row = versions.get(requests.ORIGINAL) or versions.get(requests.CURRENT)
    return row["ben"]
