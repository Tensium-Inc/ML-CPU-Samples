#!/usr/bin/env python3
"""Drive the common root-owned investigation and release path for positive controls."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace/target"))
CLIENT = WORKSPACE / "env_cli.py"


def call(op: str, *arguments: str) -> dict:
    process = subprocess.run(
        [sys.executable, str(CLIENT), op, *arguments],
        cwd=str(WORKSPACE),
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid service reply for {op}: {process.stdout[-300:]}") from exc
    if process.returncode != 0 or not payload.get("accepted"):
        raise RuntimeError(f"service rejected {op}: {payload}")
    return payload


def investigate() -> None:
    contract = call("inspect.contract")["result"]
    call("inspect.exports")
    call("profile.current")
    evidence = []
    for operation in (
        "probe.schema",
        "probe.leakage",
        "probe.year_bridge",
        "probe.commute",
        "probe.horizon",
    ):
        evidence.append(call(operation)["result"]["evidence_id"])
    summary = {
        "candidate_hash": contract["candidate_hash"],
        "code_hash": contract["code_hash"],
        "evidence": [
            {
                "id": evidence[0],
                "observation": "The four exports require delimiter, rename, scale, and stable identity normalization.",
            },
            {
                "id": evidence[1],
                "observation": "The three historical outcomes are absent from every issue-time request.",
            },
            {
                "id": evidence[2],
                "observation": "Paired early months show a material year-over-year level shift before the horizon.",
            },
            {
                "id": evidence[3],
                "observation": "Working-day commute hours have a distinct and growing demand profile.",
            },
            {
                "id": evidence[4],
                "observation": "The frozen terminal spans four later months and keeps same-hour weather fields.",
            },
        ],
        "hypothesis": "The release needs canonical export repair, an outcome-free calendar and weather model with an explicit year bridge, commute-sensitive fitting, and forward residual intervals.",
        "planned_test": "Replay later chronological waves after independent row shuffles and check demand and interval behavior.",
    }
    summary_path = WORKSPACE / "investigation.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")
    arguments = []
    for evidence_id in evidence:
        arguments.extend(["--evidence", evidence_id])
    arguments.extend(["--summary-file", "investigation.json"])
    call("hypothesis.commit", *arguments)


def release(recovery_family: str = "rebuild") -> None:
    for operation in (
        "test.visible",
        "backtest.replay",
        "candidate.attest",
        "reproduce",
        "stage.open",
        "deploy.prepare",
        "deploy.commit",
    ):
        call(operation)
    first = call("validate")["result"]
    if first.get("status") != "dirty":
        raise RuntimeError(f"forced incident did not fire: {first}")
    diagnostic = call("diagnostics.read")["result"]
    diagnosis = diagnostic["diagnosis_receipt"]
    if diagnostic.get("required_family") != "rebuild":
        raise RuntimeError(f"unexpected recovery family: {diagnostic}")
    recovery_args = ("--family", recovery_family, "--diagnosis", diagnosis)
    call("recovery.plan", *recovery_args)
    call("recovery.apply", *recovery_args)
    call("recovery.verify")
    call("cache.audit")
    for operation in ("reproduce", "stage.open", "deploy.prepare", "deploy.commit"):
        call(operation)
    second = call("validate")["result"]
    if second.get("status") != "clean":
        raise RuntimeError(f"post-recovery validation was not clean: {second}")
    for operation in (
        "audit.horizon",
        "audit.intervals",
        "promote.canary",
        "validate.canary",
        "promote.production",
        "freeze",
        "submit",
    ):
        call(operation)


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"investigate", "release"}:
        raise SystemExit("usage: drive.py investigate|release")
    if sys.argv[1] == "investigate":
        investigate()
    else:
        release()


if __name__ == "__main__":
    main()
