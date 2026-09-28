"""The corrected request table, root-side. Never reachable from the agent's workspace.

This is the executable form of the operations notes, and the notes are the
authority: where this file and a note could disagree, the note is what the task
asks for and this is what has to change.

Three questions live here.

The first is the APPLICANT KEY, and it is fully determined. The notes write the
rule out exactly and an agent that reads them can implement it with nothing left
to guess. It is here because the shipped harness gets it wrong.

The second and third are not determined anywhere, and they are the same
underlying fact seen twice: the extract carries a funding request on TWO rows,
one as filed and one as it stands after adjudication, and nothing in the file
says that the second is a restatement. So the LABEL and the FEATURES of a single
request live on different rows, and reading both off the later row hands the
model a number that the decision itself produced.
"""

from __future__ import annotations

DELIVERABLE_COLUMNS = ("funding_request_number", "label", "applicant_key",
                       "committed_cents", "filed_months",
                       "filed_commitment_cents", "filed_pre_discount_cents",
                       "filed_discount_pct")

AS_FILED = "Original"
AS_ADJUDICATED = "Current"

# The status column ships RECODED, as a de-identified extract does. The
# published E-Rate values -- Funded, Cancelled, Denied, Pending -- are memorised,
# and a column whose values the model already knows carries no work: it reads
# "Funded" and two thirds of the label rule is free before it has probed
# anything.
#
# Five tokens over four outcomes, and the split is what stops the frequencies
# answering the question:
#
#     QK7  51,464   funded
#     NN0  55,009   not adjudicated at all (every as-filed row carries it)
#     ZP2   2,746   cancelled
#     VR9     632   funded
#     VD4     632   denied
#
# VR9 and VD4 carry exactly the same number of rows and mean OPPOSITE things.
# Rarity distinguishes neither and no ordering of the tokens recovers it, so
# both have to be put to the oracle.
#
# Only ONE of them is measurable, and the asymmetry is worth stating rather than
# glossing. Reading VR9 as not-funded costs 627 requests, 5.6x the 111-request
# band. Reading VD4 as funded costs NOTHING -- every denied request carries a
# commitment of exactly zero, so the money clause already excludes it whatever
# the status token is taken to mean. VD4 is a decoy: an agent must still spend a
# call to learn which of the two tied tokens is the funded one, but only the
# VR9 half of that answer is graded. A constant the evidence cannot reach must
# not decide a run, and this one does not.
#
# All four of these are DECIDED: the extract records `pending_reason = FCDL
# Issued` on every one of them, the funding commitment decision letter going
# out, and the commitment is zero on every cancelled and every denied row.
DECIDED = {"QK7", "VR9", "ZP2", "VD4"}
FUNDED = {"QK7", "VR9"}


def cents(raw: str) -> str:
    """A money column as an exact integer number of cents, or "" when absent.

    Kept as a string of cents rather than a float because the deliverable is
    compared exactly, and two builds that both parse `10854.54` correctly must
    not disagree in the last binary place of a float.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return str(int(round(float(text) * 100)))
    except ValueError:
        return ""


def committed(row: dict) -> float | None:
    """The adjudicated commitment as a number, or None when nothing is written."""
    text = (row.get("funding_commitment_request") or "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def carried_in_a_wave(row: dict) -> bool:
    """Did a funding wave actually carry this request out?

    `wave_sequence_number` is the wave that disbursed it. It is blank on every
    Original row -- a wave is something that happens to a request after it is
    adjudicated, not something the applicant files -- and it is blank on 474
    adjudicated rows too.
    """
    return bool((row.get("wave_sequence_number") or "").strip())


def was_funded(decision: dict) -> bool:
    """Was this request actually funded, as opposed to approved on paper?

    `form_471_frn_status_name == 'Funded'` is the obvious reading and it is
    wrong on 631 requests, 1.13% of the extract, in two independent ways:

      * 465 carry a real commitment and no wave sequence number. The letter
        went out and no wave ever carried the money.
      * 165 sit in a wave with a commitment of exactly zero. The wave carried
        nothing.
      * 1 has neither.

    Both halves are above the tolerance band on their own, so a build that
    finds one and not the other still fails, and neither is recoverable from
    the status column. `Funded` is what the decision letter SAID. Funded is
    what happened.

    The extract is not ambiguous about which way this goes, but it does not
    state it either: 3,370 requests carry a wave sequence number while being
    Cancelled or Denied, so a wave is not itself a verdict, and 2,744 Cancelled
    rows carry a zero commitment, so a zero is not itself a verdict. Neither
    column decides alone and neither can be ignored. The oracle settles it one
    request at a time.
    """
    return (decision["form_471_frn_status_name"] in FUNDED
            and committed(decision) not in (None, 0.0)
            and carried_in_a_wave(decision))


def applicant_key(row: dict) -> str:
    """The entity that filed this request.

    The billed entity number, never the organisation name. Names are not unique:
    600 of them are used by more than one billed entity across 6,806 rows, so a
    name-keyed holdout puts two different applicants in one group. The number is
    stable in the other direction too -- 29 billed entities appear under more
    than one spelling of their name, and keying on the number keeps those
    together where a name would split them.
    """
    return row["ben"]


def build_reference(rows: list[dict]) -> dict[str, dict]:
    """One entry per distinct funding request.

    Each request is assembled from up to two rows, and which row each field comes
    from is the whole point:

      label            from the ADJUDICATED row, because that is where the
                       outcome exists at all. A request with no adjudicated row
                       has not been decided and is `undecided` -- 404 of them.
      the filed_* fields  from the AS FILED row. Every one of them is restated
                       on the adjudicated row, at measured rates of 25.37%,
                       15.87% and 6.19% of paired requests -- and the restated
                       commitment is exactly 0.00 on every Cancelled and every
                       Denied request, so reading it off that row is reading the
                       answer.
      committed_cents  from the ADJUDICATED row, and it is the SAME money column
                       as `filed_commitment_cents` read off the other version.
                       The two disagree on 13,855 paired requests. A build that
                       has worked out "always take the as-filed row" gets this
                       one wrong, which is the point: provenance is a decision
                       PER FIELD and not per row, because the desk needs both
                       what was asked for and what was granted.
      filed_months     from the AS FILED row, restated on 1,371. It is here so
                       that the as-filed side is not three spellings of one
                       money figure, and so a build cannot pass by treating
                       "money" as the only thing with a provenance.
      applicant_key    from either row; it is one of the seven fields the two
                       versions never disagree about.

    A request filed under no `Original` row has no as-filed values to report, and
    reports "" for each rather than borrowing the restated ones.
    """
    filed: dict[str, dict] = {}
    adjudicated: dict[str, dict] = {}
    for row in rows:
        frn = row["funding_request_number"]
        if not frn:
            continue
        if row["form_version"] == AS_FILED:
            filed.setdefault(frn, row)
        elif row["form_version"] == AS_ADJUDICATED:
            adjudicated.setdefault(frn, row)

    table: dict[str, dict] = {}
    for frn in set(filed) | set(adjudicated):
        decision = adjudicated.get(frn)
        if decision is None or decision["form_471_frn_status_name"] not in DECIDED:
            label = "undecided"
        elif was_funded(decision):
            label = "funded"
        else:
            label = "not_funded"
        as_filed = filed.get(frn)
        table[frn] = {
            "label": label,
            "applicant_key": applicant_key(as_filed or decision),
            "filed_commitment_cents": cents(as_filed["funding_commitment_request"])
                                      if as_filed else "",
            "filed_pre_discount_cents": cents(as_filed["total_pre_discount_costs"])
                                        if as_filed else "",
            "filed_discount_pct": (as_filed["dis_pct"] or "").strip() if as_filed else "",
            "committed_cents": cents(decision["funding_commitment_request"])
                               if decision else "",
            "filed_months": (as_filed["months_of_service"] or "").strip()
                            if as_filed else "",
        }
    return table
