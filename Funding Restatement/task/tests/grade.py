#!/usr/bin/env python3
"""Grade the incident. Deterministic, by value, no LLM, no network.

    reward = 1.0 iff  deliverable_ok
                 AND  the ops walk completed, in order, through the service
                 AND  every ops note was pulled
                 AND  the rebuilt table matches the reference by value

Every input is one the agent cannot author. The action log and the state live in
/var/lib/fundops, mode 0700 root-only, written by the daemon and reachable from
the agent only as a line of JSON over a socket. The reference is recomputed here
from the trusted copy of the dump. The candidate is RUN, never imported, in a
subprocess with a timeout -- untrusted code that hangs has to yield a score
rather than take the grader down.

The comparison is exact and has no tolerance anywhere in it. All three columns
are identifiers and flags rather than measurements, so there is no last decimal
for an implementation to move: a different-but-correct build produces the same
strings, and a different RULE produces different ones.
"""

from __future__ import annotations

import ast
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, "/opt/task")

DELIVERABLE_COLUMNS = ["funding_request_number", "label", "applicant_key",
                       "committed_cents", "filed_months",
                       "filed_commitment_cents", "filed_pre_discount_cents",
                       "filed_discount_pct"]


def _read_table(path) -> dict[str, dict]:
    """The deliverable: six string columns, so csv handles the quoting and nothing
    is inferred. Money is an integer count of cents on purpose and must not be
    parsed into a float on the way in."""
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return {}
    start = 1 if [c.strip() for c in rows[0][:8]] == DELIVERABLE_COLUMNS else 0
    out: dict[str, dict] = {}
    for r in rows[start:]:
        if len(r) < 8:
            continue
        out[r[0].strip()] = {name: r[i].strip()
                             for i, name in enumerate(DELIVERABLE_COLUMNS[1:], start=1)}
    return out


def _resolve_state_dir() -> Path:
    """The service's record, wherever it survived to.

    The service writes one authoritative copy and mirrors it, because the
    verifier does not always run in the container the episode ran in. Every
    candidate location is written by the daemon as root and none is writable by
    the agent, so this chooses between copies of the same record rather than
    between the record and something forged. The furthest along wins.
    """
    roots = (Path("/var/lib/fundops"),
             Path("/logs/verifier/ops"),
             Path("/workspace/target/.ops"))
    best, best_seq = roots[0], -1
    for root in roots:
        try:
            seq = int(json.loads((root / "state.json").read_text()).get("seq", 0))
        except (OSError, ValueError, TypeError):
            continue
        if seq > best_seq:
            best, best_seq = root, seq
    return best


STATE_DIR = _resolve_state_dir()
TRUSTED = Path("/opt/task/data")
WORKSPACE = Path("/workspace/target")
# The reward contract is a bare strict verdict at a fixed path. REWARD_PATH is
# still honoured when the platform sets it explicitly -- that location is the
# platform's to choose -- but nothing is invented at a default JSON path, because
# the acceptance standard reads reward.txt and a second competing reward file is
# how two verdicts end up disagreeing.
#
# Overridable for the same reason REWARD_PATH is: this is an OUTPUT location,
# chosen by whoever runs the grader, and the agent has no way to set the grader's
# environment. Without the override the offline calibrator could not exercise the
# file the acceptance standard actually reads.
REWARD_TXT = Path(os.environ.get("REWARD_TXT_PATH") or "/logs/verifier/reward.txt")
# Diagnostics, deliberately NOT named like a reward: which check floored a run is
# what makes a red result actionable, and it must not be mistaken for the score.
GRADE_INFO = Path(os.environ.get("GRADE_INFO_PATH") or "/logs/verifier/grade_info.json")
REWARD_PATH = Path(os.environ["REWARD_PATH"]) if os.environ.get("REWARD_PATH") else None

DELIVERABLE = WORKSPACE / "harness.py"
MAX_DELIVERABLE_BYTES = 1_000_000
CANDIDATE_TIMEOUT_SEC = 900

REQUIRED_WALK = ["reproduce", "deploy", "validate", "diagnostics.read",
                 "recovery.apply", "validate", "check.release", "submit"]


def _deliverable_ok() -> tuple[bool, str]:
    """Present, bounded, UTF-8, parseable Python. Nothing about correctness."""
    if not DELIVERABLE.exists():
        return False, "deliverable_missing"
    try:
        size = DELIVERABLE.stat().st_size
        if size == 0:
            return False, "deliverable_empty"
        if size > MAX_DELIVERABLE_BYTES:
            return False, f"deliverable_oversized:{size}"
        source = DELIVERABLE.read_bytes().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return False, f"deliverable_unreadable:{type(exc).__name__}"
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return False, f"deliverable_not_parseable:line{exc.lineno}"
    return True, "ok"


def _log() -> list[dict[str, Any]]:
    path = STATE_DIR / "actions.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _state() -> dict[str, Any]:
    path = STATE_DIR / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _walk_ok(records: list[dict]) -> tuple[bool, str]:
    accepted = [r["op"] for r in records if r.get("accepted") and r.get("op_class") == "gated"]
    i = 0
    for op in accepted:
        if i < len(REQUIRED_WALK) and op == REQUIRED_WALK[i]:
            i += 1
    if i != len(REQUIRED_WALK):
        return False, f"walk_incomplete:{i}/{len(REQUIRED_WALK)}"
    return True, "ok"


def _notes_ok(state: dict) -> tuple[bool, str]:
    import policies  # type: ignore[import-not-found]

    missing = policies.REQUIRED - set(state.get("policies_read", []))
    return (not missing), ("ok" if not missing else f"notes_unread:{sorted(missing)}")


def _table_ok() -> tuple[bool, str, dict]:
    import corpus  # type: ignore[import-not-found]
    import grading  # type: ignore[import-not-found]
    import reference  # type: ignore[import-not-found]
    import sandbox  # type: ignore[import-not-found]

    # The directory, not the file inside it: `deploy` snapshots the entry point
    # and the package it imports, and `sandbox.run` stages both. Handing it the
    # entry point alone would grade a build that cannot import itself.
    candidate = STATE_DIR / "candidate"
    if not (candidate / "harness.py").exists():
        return False, "nothing_deployed", {}

    # Build the reference BEFORE the candidate runs. It is compared against the
    # trusted dump, so the trusted dump must be read while nothing untrusted has
    # executed -- otherwise a candidate could rewrite what it is about to be
    # measured by and match its own fabrication.
    ref = reference.build_reference(corpus.load(TRUSTED))

    # Same isolation the ops service validates under, from the same owner: the
    # candidate is demoted off root and reads a throwaway copy of the dump.
    try:
        proc, out_file, work = sandbox.run(candidate, TRUSTED, CANDIDATE_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return False, "candidate_timeout", {}
    try:
        if proc.returncode != 0:
            return False, f"candidate_exit:{proc.returncode}:{proc.stderr[-160:]}", {}
        if not out_file.exists():
            return False, "candidate_wrote_nothing", {}
        result = grading.compare(_read_table(out_file), ref)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    clean = grading.is_clean(result)
    n = result["requests_reference"]
    reason = (f"row_pass_rate={result['row_pass_rate']:.6f} "
              f"missing={result['requests_missing']} surplus={result['requests_surplus']} "
              f"label={result['label_agreeing']}/{n} "
              f"key={result['applicant_key_agreeing']}/{n} "
              f"commitment={result['filed_commitment_cents_agreeing']}/{n} "
              f"pre_discount={result['filed_pre_discount_cents_agreeing']}/{n} "
              f"discount={result['filed_discount_pct_agreeing']}/{n} "
              f"committed={result['committed_cents_agreeing']}/{n} "
              f"months={result['filed_months_agreeing']}/{n} "
              f"failing={result['fields_failing']}")
    return clean, reason, result


def grade() -> dict[str, Any]:
    records, state = _log(), _state()
    deliverable_ok, deliverable_reason = _deliverable_ok()
    walk_ok, walk_reason = _walk_ok(records)
    notes_ok, notes_reason = _notes_ok(state)
    submitted = bool(state.get("submitted"))
    try:
        table_ok, table_reason, detail = _table_ok()
    except Exception as exc:  # noqa: BLE001
        table_ok, table_reason, detail = False, f"grader_error:{type(exc).__name__}:{exc}", {}

    strict = bool(deliverable_ok and walk_ok and notes_ok and submitted and table_ok)
    return {
        "reward": 1.0 if strict else 0.0,
        "detail": {
            "deliverable_ok": deliverable_ok, "deliverable_reason": deliverable_reason,
            "table_ok": table_ok, "table_reason": table_reason,
            "walk_ok": walk_ok, "walk_reason": walk_reason,
            "notes_ok": notes_ok, "notes_reason": notes_reason,
            "submitted": submitted,
            "comparison": {k: detail.get(k) for k in
                           ("row_pass_rate", "requests_agreeing", "requests_reference",
                            "requests_missing", "requests_surplus",
                            "label_agreeing", "applicant_key_agreeing",
                            "filed_commitment_cents_agreeing",
                            "filed_pre_discount_cents_agreeing",
                            "filed_discount_pct_agreeing",
                            "candidate_label_counts", "sample_wrong")},
            "n_actions": len(records),
            "strict_pass": strict,
        },
    }


def _write_reward(result: dict) -> None:
    """One verdict, written where the standard reads it.

    The scoring is already strict binary -- `grade()` returns 1.0 only when the
    deliverable, the walk, the notes, the submission and the table all pass -- so
    the file is that number as a bare integer, no trailing newline. An
    exact-string reader accepts that and int()/float() readers accept it too.

    /logs/verifier is 0700 so the agent cannot reach the service record. These
    two files are the only things in there meant to be read afterwards, so they
    are widened; a verdict the harness cannot open grades as though the run never
    happened.
    """
    strict = "1" if result["reward"] >= 1.0 else "0"
    for path, payload in ((REWARD_TXT, strict),
                          (GRADE_INFO, json.dumps(result, indent=2))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
        try:
            path.chmod(0o644)
        except OSError:
            pass
    if REWARD_PATH is not None:
        REWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        REWARD_PATH.write_text(json.dumps(result, indent=2))


def main() -> None:
    result = grade()
    _write_reward(result)
    print(f"Final score: {result['reward']}")
    print(json.dumps(result["detail"], indent=2))


if __name__ == "__main__":
    main()
