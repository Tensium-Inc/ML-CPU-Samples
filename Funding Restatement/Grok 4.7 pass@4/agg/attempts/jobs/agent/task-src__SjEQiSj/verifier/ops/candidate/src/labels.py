"""What outcome a funding request had.

The extract records a status per form version. Turning that into the label the
desk signs off is a decision about what each status MEANS, not a rename.
"""

from __future__ import annotations


def label_for(versions: dict[str, dict]) -> str:
    """funded | not_funded | undecided.

    A request with no adjudicated (Current) version was never ruled on.

    On the adjudicated version the status token is what the decision letter
    said, not what the fund did. A request was funded only when a funding wave
    was actually issued and the commitment that remains is a positive amount.
    A wave with the commitment zeroed, or an adjudicated row that never entered
    a wave, is a decision that did not fund the request. Two tokens can name
    the same outcome; the wave and the remaining commitment are what separate
    them.
    """
    current = versions.get("Current")
    if current is None:
        return "undecided"
    if not current.get("wave_sequence_number"):
        return "not_funded"
    commitment = (current.get("funding_commitment_request") or "").strip()
    if not commitment:
        return "not_funded"
    try:
        amount = float(commitment)
    except ValueError:
        return "not_funded"
    if amount > 0:
        return "funded"
    return "not_funded"


def label(row: dict) -> str:
    """Compatibility wrapper for a single row. Prefer label_for."""
    return label_for({"Current": row} if row.get("form_version") == "Current" else {"Original": row})
