"""The applicant key: the billed entity number, never the name."""
from __future__ import annotations


def applicant_key(row):
    return row["ben"]
