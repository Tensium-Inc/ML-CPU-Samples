"""What outcome a funding request had.

The extract records a status per form version, and the status column ships
RECODED: its tokens are not a published code list and none of them is the
label. The label is settled against what the extract records actually
HAPPENED to the request, confirmed case by case against the desk's own
adjudications:

  * A request with no adjudicated (`Current`) version was never ruled on by
    anybody: `undecided`. Nothing on the filed version changes that.
  * A request whose adjudicated version never entered a funding wave
    (`wave_sequence_number` empty) did not come out of the process with a
    commitment, whatever number the row carries: `not_funded`.
    (Adjudicated: e.g. FRN 2499059845, positive figure, no wave -> not_funded.)
  * Otherwise the money column records what the fund did: a positive
    commitment is `funded`, a zero or absent one is `not_funded`.
    (Adjudicated: 2499000008 pos -> funded; 2499000089, 2499000028,
    2499003144 zero -> not_funded; 2499022438 empty -> not_funded;
    2499059160, 2499016356 pos+wave -> funded.)

Neither the status token nor any single column decides this on its own; the
letter said many things, but the wave and the committed amount are the record
of what the fund did.
"""

from __future__ import annotations

from . import requests


def label(current: dict | None) -> str:
    """funded | not_funded | undecided, from the adjudicated version (or None)."""
    if current is None:
        return "undecided"
    if not current.get("wave_sequence_number"):
        return "not_funded"
    committed = requests.cents(current.get("funding_commitment_request", ""))
    if committed and int(committed) > 0:
        return "funded"
    return "not_funded"
