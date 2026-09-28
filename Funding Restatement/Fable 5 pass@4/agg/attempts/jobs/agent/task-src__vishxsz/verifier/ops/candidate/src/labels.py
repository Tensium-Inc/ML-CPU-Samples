"""What outcome a funding request had.

A status is what the decision letter SAID. It is not a record of what the fund
DID -- and the label reports what the fund did. Two columns on the adjudicated
version carry that record, and neither decides it alone:

    funding_commitment_request   the money the adjudicated version carries
    wave_sequence_number         the funding wave that disbursed a commitment

Adjudicated against the oracle, the pair wins every disagreement with the
status token:

    * a positive figure on a version that carries a funding wave is `funded`,
      whichever status token the letter used and whether or not it was appealed;
    * a zeroed or blank figure is `not_funded`, whichever token the letter
      used, appealed or not;
    * a positive figure on a version with NO funding wave (an appeal wave only)
      never went out through a wave, and is `not_funded` -- the letter restates
      money that the fund did not commit.

A request with no adjudicated version at all has not been decided by anybody
and is `undecided`. There are a few hundred.
"""

from __future__ import annotations

from . import requests


def label(entry: dict) -> str:
    """funded | not_funded | undecided, for one collected request.

    `entry` is one value of `requests.collect`: the filed and adjudicated
    versions of a single funding request.
    """
    adjudicated = entry["adjudicated"]
    if adjudicated is None:
        return "undecided"
    committed = requests.cents(adjudicated["funding_commitment_request"])
    if committed and int(committed) > 0 and adjudicated["wave_sequence_number"]:
        return "funded"
    return "not_funded"
