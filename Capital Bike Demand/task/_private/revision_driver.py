#!/usr/bin/env python3
"""Exercise the optional bounded revision path in local calibration."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


TASK = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("bike_drive", TASK / "solution" / "drive.py")
DRIVE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(DRIVE)


def before() -> None:
    for operation in (
        "test.visible",
        "backtest.replay",
        "candidate.attest",
        "reproduce",
        "stage.open",
        "deploy.prepare",
        "deploy.commit",
    ):
        DRIVE.call(operation)
    forced = DRIVE.call("validate")["result"]
    if forced.get("signal") != "runtime_snapshot_stale":
        raise RuntimeError(f"forced incident missing: {forced}")
    diagnostic = DRIVE.call("diagnostics.read")["result"]
    family = diagnostic["required_family"]
    receipt = diagnostic["diagnosis_receipt"]
    recovery = ("--family", family, "--diagnosis", receipt)
    DRIVE.call("recovery.plan", *recovery)
    DRIVE.call("recovery.apply", *recovery)
    DRIVE.call("recovery.verify")
    DRIVE.call("cache.audit")
    for operation in ("reproduce", "stage.open", "deploy.prepare", "deploy.commit"):
        DRIVE.call(operation)
    dirty = DRIVE.call("validate")["result"]
    if dirty.get("signal") != "protected_behavior_dirty":
        raise RuntimeError(f"revision gate missing: {dirty}")


def after() -> None:
    for operation in (
        "candidate.revise",
        "test.visible",
        "backtest.replay",
        "candidate.attest",
        "reproduce",
        "stage.open",
        "deploy.prepare",
        "deploy.commit",
    ):
        DRIVE.call(operation)
    clean = DRIVE.call("validate")["result"]
    if clean.get("status") != "clean":
        raise RuntimeError(f"revised candidate not clean: {clean}")
    for operation in (
        "audit.horizon",
        "audit.intervals",
        "promote.canary",
        "validate.canary",
        "promote.production",
        "freeze",
        "submit",
    ):
        DRIVE.call(operation)


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"before", "after"}:
        raise SystemExit("usage: revision_driver.py before|after")
    if sys.argv[1] == "before":
        before()
    else:
        after()


if __name__ == "__main__":
    main()
