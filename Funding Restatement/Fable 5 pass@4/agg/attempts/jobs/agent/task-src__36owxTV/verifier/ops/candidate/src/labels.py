"""What outcome a funding request had.

A status is what the decision letter SAID. It is not a record of what the fund
did. Two columns of the adjudicated version record what the fund did with the
money: `funding_commitment_request` (how much was granted) and
`wave_sequence_number` (the funding wave that committed it -- money that was
never in a wave was never committed). Adjudicated ground truth (11 oracle
calls covering every status-token x commitment x wave cell of the extract)
agrees with the money and never with the token:

  - positive commitment carried in a funding wave -> `funded`, whatever token
    the letter carries (QK7 and VR9 both appear);
  - an adjudicated version with a zero or absent commitment, or one whose
    positive figure never entered a funding wave -> `not_funded`: someone ruled,
    and the fund granted nothing;
  - no adjudicated version at all -> `undecided`: nobody ever ruled on it.
"""

from __future__ import annotations

from . import requests


def label(versions: dict[str, dict]) -> str:
    """funded | not_funded | undecided, from every version of one request."""
    current = versions.get(requests.CURRENT)
    if current is None:
        return "undecided"
    committed = requests.cents(current["funding_commitment_request"])
    if committed and int(committed) > 0 and current["wave_sequence_number"]:
        return "funded"
    return "not_funded"
