"""What outcome a funding request had.

The extract records a status per form version. Turning that into the label the
desk signs off is a decision about what each status MEANS, not a rename.
"""

from __future__ import annotations

FUNDED = "Funded"


def label(row: dict) -> str:
    """funded | not_funded | undecided.

    TODO(desk): `Cancelled` is currently treated as though nobody ever ruled on
    the request. The merge review argued about that and it was never settled; the
    `decisions` ops note says what to look at in the extract to settle it.
    """
    status = row.get("form_471_frn_status_name", "")
    if status == FUNDED:
        return "funded"
    if status == "Denied":
        return "not_funded"
    return "undecided"
