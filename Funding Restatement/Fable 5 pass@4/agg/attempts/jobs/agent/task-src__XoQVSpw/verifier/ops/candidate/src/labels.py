"""What outcome a funding request had.

The extract records a status per form version. Turning that into the label the
desk signs off is a decision about what each status MEANS, not a rename.

A status is what the decision letter SAID. It is not a record of what the fund
did. The fund's own record is the pair of columns on the adjudicated version:
`funding_commitment_request` (the money as committed) and
`wave_sequence_number` (the funding wave the commitment was issued in). A
request was funded when money was committed AND a funding wave carried it;
adjudicated any other way it was not funded, whatever the letter said. Both
directions were confirmed case-by-case against the desk's own adjudications:
a funded-status letter with the money zeroed out, or with no funding wave, is
not_funded; a decided request with committed money and a wave is funded even
when the status token is one of the rare ones.

A request with no adjudicated version at all has not been decided by anybody
and is `undecided`. That is a different fact from a decided request that got
nothing.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _amount(raw: str) -> Decimal | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def label(current: dict | None) -> str:
    """funded | not_funded | undecided.

    `current` is the adjudicated ("Current") version of the request, or None
    when the extract carries no adjudicated version.
    """
    if current is None:
        return "undecided"
    committed = _amount(current.get("funding_commitment_request", ""))
    wave = (current.get("wave_sequence_number") or "").strip()
    if committed is not None and committed > 0 and wave:
        return "funded"
    return "not_funded"
