"""What outcome a funding request had.

The extract records a status per form version. Turning that into the label the
desk signs off is a decision about what each status MEANS, not a rename.
"""

from __future__ import annotations


def label(row: dict | None) -> str:
    """funded | not_funded | undecided.

    A status token is what a decision letter said, and this extract's tokens are
    recoded so they cannot be read as a published code list. What the fund did
    is the committed amount on the adjudicated version of the request.

    No adjudicated version means nobody has ruled: ``undecided``. An adjudicated
    version whose commitment is blank or zero did not receive money:
    ``not_funded``. A positive commitment is what the fund actually granted:
    ``funded``.
    """
    if not row:
        return "undecided"
    raw = (row.get("funding_commitment_request") or "").strip()
    if not raw:
        return "not_funded"
    try:
        amount = float(raw)
    except ValueError:
        return "not_funded"
    if amount > 0:
        return "funded"
    return "not_funded"
