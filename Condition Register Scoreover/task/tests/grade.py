#!/usr/bin/env python3
"""Strict grader.

    strict = terminal_correct AND gate_walk_ok AND forced_recovery_ok AND depth_ok
    reward = 1.0 if strict else 0.0

A boolean conjunction; the partials are diagnostic and never compensate. The reward is written
to a FILE, which is the contract the harness reads. A grader that only prints reports 0.000 on a
fully correct run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else False


def _pinned(var: str, literal: str) -> Path:
    return Path(literal) if _ROOT else Path(os.environ.get(var, literal))


WORKSPACE = _pinned("WORKSPACE_DIR", "/workspace/target")
STATE_DIR = _pinned("ENVD_STATE", "/var/lib/envstate")
REWARD_TXT = _pinned("REWARD_PATH", "/logs/verifier/reward.txt")
PROBE = Path(__file__).resolve().parent / "terminal_probe.py"
PROBE_TIMEOUT_SEC = 1800

ACTIONS = STATE_DIR / "actions.jsonl"
STATE = STATE_DIR / "state.json"

REQUIRED_WALK = ["rehearse", "deploy.prepare", "deploy.commit", "checkpoint", "incident.read",
                 "remediate", "checkpoint", "canary.open", "canary.read", "cutover.commit"]
REMEDIATION_FAMILY = "config_drift"

# Corroborating floors, not discriminators: the required walk already forces ten gated ops and
# the gold trajectories land at 17 to 24 accepted actions.
MIN_TOTAL_ACTIONS = 12
MIN_OBSERVATIONS = 2


def load_actions() -> List[Dict[str, Any]]:
    if not ACTIONS.exists():
        return []
    out = []
    for line in ACTIONS.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def accepted_ops(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [a for a in actions if a.get("accepted") and a.get("op_class") == "operational"]


def gate_walk_ok(actions: List[Dict[str, Any]]) -> Tuple[bool, str]:
    ops = accepted_ops(actions)
    names = [a["op"] for a in ops]
    i = 0
    for name in names:
        if i < len(REQUIRED_WALK) and name == REQUIRED_WALK[i]:
            i += 1
    if i != len(REQUIRED_WALK):
        return False, f"walk_incomplete:{i}/{len(REQUIRED_WALK)}:{'>'.join(names[-6:])}"
    remediations = [a for a in ops if a["op"] == "remediate"]
    if not remediations or remediations[-1].get("payload", {}).get("family") != REMEDIATION_FAMILY:
        return False, "remediation_family_mismatch"
    seen = clean_after = False
    for a in ops:
        if a["op"] == "remediate":
            seen = True
        elif seen and a["op"] == "checkpoint" and a.get("payload", {}).get("status") == "clean":
            clean_after = True
    if not clean_after:
        return False, "no_clean_checkpoint_after_remediation"
    verdicts = [a for a in ops if a["op"] == "canary.read"]
    if not verdicts or verdicts[-1].get("payload", {}).get("verdict") != "pass":
        return False, "canary_did_not_pass"
    if names[-1] != "cutover.commit":
        return False, f"walk_does_not_end_at_cutover:{names[-1]}"
    return True, "ok"


def forced_recovery_ok(actions: List[Dict[str, Any]]) -> Tuple[bool, str]:
    dirty = diagnosed = repaired = False
    for a in accepted_ops(actions):
        payload = a.get("payload", {})
        if a["op"] == "checkpoint" and payload.get("status") == "dirty":
            dirty = True
        elif a["op"] == "incident.read" and payload.get("family") == REMEDIATION_FAMILY:
            diagnosed = diagnosed or dirty
        elif a["op"] == "remediate" and payload.get("family") == REMEDIATION_FAMILY:
            repaired = repaired or diagnosed
    if not dirty:
        return False, "injected_failure_never_observed"
    if not diagnosed:
        return False, "failure_never_diagnosed"
    if not repaired:
        return False, "failure_never_repaired_after_diagnosis"
    return True, "ok"


def depth_ok(actions: List[Dict[str, Any]]) -> Tuple[bool, str]:
    acc = [a for a in actions if a.get("accepted")]
    obs = [a for a in acc if a.get("op_class") == "observation"]
    if len(acc) < MIN_TOTAL_ACTIONS:
        return False, f"too_few_accepted_actions:{len(acc)}<{MIN_TOTAL_ACTIONS}"
    if len(obs) < MIN_OBSERVATIONS:
        return False, f"too_few_observations:{len(obs)}<{MIN_OBSERVATIONS}"
    return True, "ok"


def terminal_correct() -> Tuple[bool, str, Dict[str, Any]]:
    env = os.environ.copy()
    env.setdefault("WORKSPACE_DIR", str(WORKSPACE))
    env.setdefault("ENVD_STATE", str(STATE_DIR))
    try:
        proc = subprocess.run([sys.executable, str(PROBE)], env=env, cwd=str(PROBE.parent),
                              capture_output=True, text=True, timeout=PROBE_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return False, "probe_timeout", {}
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    if not lines:
        return False, f"probe_no_output:{proc.stderr[-200:]}", {}
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return False, f"probe_unparseable:{exc}", {}
    return bool(payload.get("healthy")), str(payload.get("reason", "unhealthy")), payload


def grade() -> Dict[str, Any]:
    if not STATE.exists():
        return {"reward": 0.0, "info": {
            "error": "no_environment_state",
            "detail": (f"{STATE} is missing: the release service never ran, so no trajectory "
                       "was recorded. Check that the image entrypoint started envd."),
        }}
    state = json.loads(STATE.read_text())
    actions = load_actions()

    walk, walk_reason = gate_walk_ok(actions)
    recovery, recovery_reason = forced_recovery_ok(actions)
    depth, depth_reason = depth_ok(actions)
    terminal, terminal_reason, probe = terminal_correct()
    strict = bool(walk and recovery and depth and terminal)

    return {"reward": 1.0 if strict else 0.0, "info": {
        "strict_pass": strict,
        "terminal_correct": terminal, "terminal_reason": terminal_reason,
        "terminal": probe.get("terminal", {}),
        "gate_walk_ok": walk, "gate_reason": walk_reason,
        "forced_recovery_ok": recovery, "recovery_reason": recovery_reason,
        "depth_ok": depth, "depth_reason": depth_reason,
        "counts": {
            "accepted_actions": sum(1 for a in actions if a.get("accepted")),
            "rejected_actions": sum(1 for a in actions if not a.get("accepted")),
            "observations": sum(1 for a in actions if a.get("accepted")
                                and a.get("op_class") == "observation"),
            "releases_committed": state.get("deploy_count", 0),
            "checkpoints": state.get("checkpoint_count", 0),
            "canaries": state.get("canary_count", 0),
            "wrong_remediations": state.get("wrong_recoveries", 0),
        },
        "rejections": sorted({
            f"{a.get('op')}:{a.get('payload', {}).get('error')}"
            for a in actions if not a.get("accepted") and a.get("payload", {}).get("error")
        })[:8],
        "frozen_digest": state.get("frozen_digest"),
    }}


def main() -> None:
    result = grade()
    reward = 1 if float(result["reward"]) >= 1.0 else 0
    try:
        REWARD_TXT.parent.mkdir(parents=True, exist_ok=True)
        REWARD_TXT.write_text(f"{reward}\n")
    except OSError as exc:
        print(f"FATAL: could not write the reward file {REWARD_TXT}: {exc}", file=sys.stderr)
        raise
    print(f"Final score: {reward}")
    print(json.dumps(result["info"], indent=2, default=str))


if __name__ == "__main__":
    main()
