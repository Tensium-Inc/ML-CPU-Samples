"""One reader for the pinned extract. Both sides of the task use it.

The service, the verifier and the reference all have to agree about what a row IS
before they can disagree about what it means, so the parse lives here once rather
than three times.

Every row of the published extract is here, all twenty-two columns. What is
withheld is a judgement and never the data.
"""

from __future__ import annotations

import csv
import gzip
from pathlib import Path

EXTRACT_NAME = "erate_frn_status_fy2024.csv.gz"

COLUMNS = ("application_number", "funding_request_number", "form_version",
           "form_471_frn_status_name", "ben", "organization_name",
           "organization_entity_type_name", "state", "form_471_service_type_name",
           "contract_type_name", "bid_count", "dis_pct", "funding_commitment_request",
           "total_pre_discount_costs", "months_of_service",
           "is_based_on_state_master_contract", "was_fcc_form_470_posted",
           "is_certified_in_window", "wave_sequence_number", "appeal_wave_number",
           "pending_reason", "funding_year")


def load(data_root) -> list[dict]:
    """Every row of the extract, in file order, values verbatim.

    A LIST and not a dict: the extract carries the same funding request on more
    than one row, so there is no column that keys it. Handing back a mapping
    would mean choosing which row wins, and that choice is the task.
    """
    path = Path(data_root) / EXTRACT_NAME
    rows: list[dict] = []
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append({c: (row.get(c) or "").strip() for c in COLUMNS})
    return rows
