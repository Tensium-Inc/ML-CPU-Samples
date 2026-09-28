#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path


task = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("bike_drive", task / "solution" / "drive.py")
drive = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(drive)

for operation in (
    "test.visible",
    "backtest.replay",
    "candidate.attest",
    "reproduce",
    "stage.open",
    "deploy.prepare",
    "deploy.commit",
):
    drive.call(operation)
drive.call("validate")
diagnosis = drive.call("diagnostics.read")["result"]["diagnosis_receipt"]
drive.call("recovery.plan", "--family", "restart", "--diagnosis", diagnosis)
