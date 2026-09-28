#!/usr/bin/env python3
"""Lay the pinned extract into the workspace and the trusted copy. Deterministic.

Nothing here invents a row. Every row is a real USAC E-Rate FRN Status record for
funding year 2024, and the script only selects columns, drops the contact fields,
and decides where the bytes go.

The workspace and the trusted copy get the SAME bytes. What is withheld is the
corrected request table -- which rows are one request, which row each field is
read from, and which requests have been decided -- and that exists only in
`reference.py`, reachable only through the rationed service.

The script refuses to write anything until it has rebuilt the reference and
checked every number this task was designed around. A generator that has drifted
from the reference lays down a corpus for a task that no longer exists.

**Columns dropped, deliberately.** `cnct_email` carries a real address on all
110,483 rows and `crn_data` embeds more inside a packed field. `narrative`,
`nickname`, `fcdl_comment_app`, `fcdl_comment_frn` and `restriction_citation` are
free text written by applicants. None is needed and none should be shipped.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "environment/backend"
sys.path.insert(0, str(BACKEND))

import corpus      # noqa: E402
import reference   # noqa: E402

SOURCE_URL = ("https://datahub.usac.org/resource/qdmp-ygft.csv"
              "?$where=funding_year%3D%272024%27&$limit=300000")
# The digest of the SUBSET this script writes, not of the upstream pull. USAC is a
# live query and restates rows as waves are issued, so an upstream digest is good
# for one session and no longer -- the same trap that moved the CFPB slice under a
# recorded hash while its byte count stayed identical. The mirror is the artifact
# of record.
EXTRACT_SHA256 = "b4dd1b7a639a0beec253746d86710cf67aea880ed30d4f6b562cb89351fc5022"

EXPECT = {
    "rows": 110_483,
    "requests": 55_878,
    "paired": 54_605,
    "filed_only": 404,
    "adjudicated_only": 869,
    "funded": 52_096,
    "not_funded": 3_378,
    "undecided": 404,
    "restated_commitment": 13_855,
    "applicants": 21_462,
    "names_used_by_more_than_one_applicant": 600,
}


def selfcheck(rows: list[dict]) -> dict:
    """Rebuild the reference and refuse to proceed unless it is the task we designed."""
    table = reference.build_reference(rows)
    filed = {r["funding_request_number"] for r in rows if r["form_version"] == "Original"}
    adj = {r["funding_request_number"] for r in rows if r["form_version"] == "Current"}
    by_frn_filed = {r["funding_request_number"]: r for r in rows
                    if r["form_version"] == "Original"}
    by_frn_adj = {r["funding_request_number"]: r for r in rows
                  if r["form_version"] == "Current"}
    restated = sum(1 for f in filed & adj
                   if reference.cents(by_frn_filed[f]["funding_commitment_request"])
                   != reference.cents(by_frn_adj[f]["funding_commitment_request"]))
    names: dict[str, set[str]] = {}
    for r in rows:
        names.setdefault(r["organization_name"], set()).add(r["ben"])

    got = {
        "rows": len(rows),
        "requests": len(table),
        "paired": len(filed & adj),
        "filed_only": len(filed - adj),
        "adjudicated_only": len(adj - filed),
        "funded": sum(1 for v in table.values() if v["label"] == "funded"),
        "not_funded": sum(1 for v in table.values() if v["label"] == "not_funded"),
        "undecided": sum(1 for v in table.values() if v["label"] == "undecided"),
        "restated_commitment": restated,
        "applicants": len({r["ben"] for r in rows}),
        "names_used_by_more_than_one_applicant": sum(1 for v in names.values() if len(v) > 1),
    }
    bad = {k: (EXPECT[k], v) for k, v in got.items() if EXPECT[k] != v}
    if bad:
        lines = "\n".join(f"  {k}: expected {a:,} observed {b:,}" for k, (a, b) in bad.items())
        raise SystemExit(f"reference no longer matches the measured task:\n{lines}")
    return table


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", default=str(Path.home() / ".cache/cpuml-corpora/erate"))
    ap.add_argument("--task-root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    src = Path(args.cache) / "fy2024.csv"
    if not src.exists():
        raise SystemExit(f"missing {src}\n  curl -o {src} '{SOURCE_URL}'")

    with src.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        kept = [{c: (row.get(c) or "") for c in corpus.COLUMNS} for row in reader]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(corpus.COLUMNS))
    writer.writeheader()
    writer.writerows(kept)
    body = buf.getvalue().encode()
    digest = hashlib.sha256(body).hexdigest()
    if digest != EXTRACT_SHA256:
        raise SystemExit(
            f"extract digest mismatch\n  expected {EXTRACT_SHA256}\n  observed {digest}\n"
            "USAC restates rows as funding waves are issued, so a fresh pull will not "
            "reproduce this. Every measured number below was taken against the pinned "
            "extract and none of them carry over.")

    root = Path(args.task_root)
    workspace = root / "environment/workspace/data"
    trusted = root / "environment/trusted"
    workspace.mkdir(parents=True, exist_ok=True)
    trusted.mkdir(parents=True, exist_ok=True)
    for target in (workspace, trusted):
        with gzip.GzipFile(filename="", mode="wb", mtime=0,
                           fileobj=(target / corpus.EXTRACT_NAME).open("wb")) as gz:
            gz.write(body)

    rows = corpus.load(trusted)
    selfcheck(rows)
    size = (trusted / corpus.EXTRACT_NAME).stat().st_size
    print(f"extract      {EXPECT['rows']:>9,} rows -> trusted AND workspace "
          f"(identical bytes, {size:,} gz)")
    print(f"requests     {EXPECT['requests']:>9,}   "
          f"({EXPECT['paired']:,} filed AND adjudicated, "
          f"{EXPECT['filed_only']:,} filed only, {EXPECT['adjudicated_only']:,} adjudicated only)")
    print(f"labels       funded {EXPECT['funded']:,}  not_funded {EXPECT['not_funded']:,}  "
          f"undecided {EXPECT['undecided']:,}")
    print(f"restatement  {EXPECT['restated_commitment']:>9,} requests whose commitment moved "
          f"between the two rows")
    print(f"applicants   {EXPECT['applicants']:>9,}   "
          f"({EXPECT['names_used_by_more_than_one_applicant']} names used by more than one)")
    print("withheld: the request table, which appears in neither copy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
