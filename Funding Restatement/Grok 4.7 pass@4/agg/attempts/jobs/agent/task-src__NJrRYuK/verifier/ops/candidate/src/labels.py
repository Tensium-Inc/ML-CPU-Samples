"""What outcome a funding request had.

The extract records a status per form version. Turning that into the label the
desk signs off is a decision about what each status MEANS, not a rename.
"""

from __future__ import annotations


def label_from_versions(original: dict | None, current: dict | None) -> str:
    """funded | not_funded | undecided.

    A status token is what a decision letter said, and this extract's tokens are
    recoded. What the fund did is the commitment on the adjudicated version:

      * no Current version at all — nobody has ruled — ``undecided``
      * Current commitment strictly positive — money was granted — ``funded``
      * Current commitment zero or absent — nothing was granted — ``not_funded``

    Zero and absent are both "nothing granted". They are not the same fact for
    the money columns, which keep that distinction themselves.
    """
    if current is None:
        return "undecided"
    raw = (current.get("funding_commitment_request") or "").strip()
    if not raw:
        return "not_funded"
    try:
        granted = float(raw)
    except ValueError:
        return "not_funded"
    if granted > 0:
        return "funded"
    return "not_funded"


def label(row: dict) -> str:
    """Label from a single row.

    Kept for callers that already hold the row they want judged. A row that is
    not the adjudicated version has not been decided.
    """
    if row.get("form_version") != "Current":
        return "undecided"
    return label_from_versions(None, row)
