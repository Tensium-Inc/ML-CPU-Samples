"""What outcome a funding request had.

The extract records a status per form version. Turning that into the label the
desk signs off is a decision about what each status MEANS, not a rename.
"""

from __future__ import annotations

# Recoded status tokens on the adjudicated version. The scheme is not a
# bijection: two tokens name the funded letter and two name the denied letter.
# Which pair is which is settled by the commitment column, not by the token.
FUNDED_LETTERS = frozenset({"QK7", "VR9"})
DENIED_LETTERS = frozenset({"ZP2", "VD4"})


def _amount(raw: str):
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def label_from_versions(versions: dict[str, dict]) -> str:
    """funded | not_funded | undecided.

    No adjudicated version means nobody has ruled. On the adjudicated version
    the status is what the letter said and the commitment is what the fund did,
    and neither column decides alone:

    * a funded letter with money actually committed is funded;
    * a funded letter whose commitment was zeroed is not funded — the letter
      and the money disagree, and the money is the rule in that direction;
    * a denied letter is not funded even where a rounding leaves a cent, which
      is the disagreement in the other direction and is noise;
    * a letter token outside both pairs is the withdrawn-before-ruling case
      and stays undecided.
    """
    current = versions.get("Current")
    if current is None:
        return "undecided"
    status = current.get("form_471_frn_status_name", "")
    amount = _amount(current.get("funding_commitment_request", ""))
    if status in FUNDED_LETTERS:
        if amount is not None and amount > 0:
            return "funded"
        return "not_funded"
    if status in DENIED_LETTERS:
        return "not_funded"
    return "undecided"


def label(row: dict) -> str:
    """Label of a single row. An as-filed row has not been decided."""
    if row.get("form_version") != "Current":
        return "undecided"
    return label_from_versions({"Current": row})
