#!/usr/bin/env python3
"""Strict grader for the signed bike forecast incident and terminal values."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


WORKSPACE = Path("/workspace/target")
STATE_DIR = Path("/var/lib/capital-bike-task")
REWARD_PATH = Path("/logs/verifier/reward.txt")
ACTIONS = STATE_DIR / "actions.jsonl"
KEY = STATE_DIR / "action.key"
STATE = STATE_DIR / "state.json"
TERMINAL = STATE_DIR / "terminal.json"
CANDIDATE = STATE_DIR / "terminal_candidate"
HISTORY = STATE_DIR / "terminal_history.csv"
PROBE = Path(__file__).with_name("terminal_probe.py")
SOURCE_TERMINAL = Path(__file__).with_name("terminal.csv")
PRIVATE_TERMINAL = STATE_DIR / "verifier_terminal.csv"

INVESTIGATION = [
    "inspect.contract",
    "inspect.exports",
    "profile.current",
    "probe.schema",
    "probe.leakage",
    "probe.year_bridge",
    "probe.commute",
    "probe.horizon",
    "hypothesis.commit",
]
RELEASE = [
    "test.visible",
    "backtest.replay",
    "candidate.attest",
    "reproduce",
    "stage.open",
    "deploy.prepare",
    "deploy.commit",
    "validate",
    "diagnostics.read",
    "recovery.plan",
    "recovery.apply",
    "recovery.verify",
    "cache.audit",
    "reproduce",
    "stage.open",
    "deploy.prepare",
    "deploy.commit",
    "validate",
    "audit.horizon",
    "audit.intervals",
    "promote.canary",
    "validate.canary",
    "promote.production",
    "freeze",
    "submit",
]
REVISION = [
    "candidate.revise",
    "test.visible",
    "backtest.replay",
    "candidate.attest",
    "reproduce",
    "stage.open",
    "deploy.prepare",
    "deploy.commit",
    "validate",
]


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _load_actions() -> list[dict[str, Any]]:
    if not ACTIONS.is_file() or ACTIONS.is_symlink() or ACTIONS.stat().st_size > 2_000_000:
        return []
    try:
        values = [json.loads(line) for line in ACTIONS.read_text(encoding="ascii").splitlines()]
    except Exception:
        return []
    return values if all(isinstance(value, dict) for value in values) else []


def _chain(actions: list[dict[str, Any]]) -> tuple[bool, str]:
    if not actions:
        return False, "action_history_missing"
    try:
        if not KEY.is_file() or KEY.is_symlink() or len(KEY.read_bytes()) != 32:
            return False, "action_key_invalid"
        key = KEY.read_bytes()
    except OSError:
        return False, "action_key_unreadable"
    previous = "GENESIS"
    for expected, action in enumerate(actions, start=1):
        if action.get("seq") != expected or action.get("prev") != previous:
            return False, f"action_chain_invalid:{expected}"
        signature = action.get("signature")
        body = dict(action)
        body.pop("signature", None)
        wanted = hmac.new(key, _json_bytes(body), hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(signature, wanted):
            return False, f"action_signature_invalid:{expected}"
        previous = hashlib.sha256(_json_bytes(action)).hexdigest()
    try:
        persisted = json.loads(STATE.read_text(encoding="ascii"))
    except Exception:
        return False, "action_state_parse"
    if persisted.get("sequence") != len(actions) or persisted.get("chain_hash") != previous:
        return False, "action_state_head_mismatch"
    return True, "ok"


def _walk(actions: list[dict[str, Any]]) -> tuple[bool, str, dict[str, int]]:
    accepted = [action for action in actions if action.get("accepted")]
    operations = [str(action.get("op")) for action in accepted]
    counts = {name: operations.count(name) for name in sorted(set(operations))}
    direct = INVESTIGATION + RELEASE
    revised = INVESTIGATION + RELEASE[:18] + REVISION + RELEASE[18:]
    if operations not in (direct, revised):
        return False, "ordered_walk_invalid", counts
    if len(accepted) not in (34, 43):
        return False, f"accepted_action_depth:{len(accepted)}", counts
    for action in accepted:
        if action.get("op") not in {"candidate.attest", "candidate.revise"}:
            continue
        payload = action.get("payload", {})
        if int(payload.get("changed_count", 0)) < 2 or len(payload.get("changed_files", [])) < 2:
            return False, "multi_file_attestation_missing", counts
    release = accepted[len(INVESTIGATION) :]

    def payload(operation: str, occurrence: int = 0) -> dict[str, Any]:
        matches = [action.get("payload", {}) for action in release if action.get("op") == operation]
        return matches[occurrence] if len(matches) > occurrence else {}

    validations = [action.get("payload", {}) for action in release if action.get("op") == "validate"]
    first_validate = validations[0] if validations else {}
    final_validate = validations[-1] if validations else {}
    diagnosis = payload("diagnostics.read")
    plan = payload("recovery.plan")
    apply = payload("recovery.apply")
    verify = payload("recovery.verify")
    horizon = payload("audit.horizon")
    intervals = payload("audit.intervals")
    canary = payload("validate.canary")
    freeze = payload("freeze")
    receipt = diagnosis.get("diagnosis_receipt")
    if first_validate.get("status") != "dirty" or first_validate.get("signal") != "runtime_snapshot_stale":
        return False, "forced_dirty_validation_missing", counts
    if not isinstance(receipt, str) or not receipt.startswith("diag-"):
        return False, "diagnosis_receipt_missing", counts
    if diagnosis.get("required_family") != "rebuild":
        return False, "required_recovery_family_missing", counts
    for payload, status in ((plan, "planned"), (apply, "applied")):
        if payload.get("family") != "rebuild" or payload.get("diagnosis_receipt") != receipt or payload.get("status") != status:
            return False, "evidence_bound_recovery_missing", counts
    if len(validations) not in (2, 3) or final_validate.get("status") != "clean":
        return False, "post_recovery_validation_missing", counts
    if len(validations) == 3:
        if validations[1].get("status") != "dirty" or validations[1].get("signal") != "protected_behavior_dirty":
            return False, "bounded_revision_trigger_missing", counts
    if verify.get("status") != "verified":
        return False, "recovery_verification_missing", counts
    if horizon.get("row_order_invariant") is not True or intervals.get("status") != "clean":
        return False, "protected_audit_missing", counts
    if canary.get("status") != "clean":
        return False, "clean_canary_missing", counts
    if int(freeze.get("runtime_generation", -1)) != 2 or freeze.get("immutable") is not True:
        return False, "terminal_freeze_invalid", counts
    return True, "ok", counts


def _bundle_hash(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        return ""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or (relative.parts and relative.parts[0] == "results"):
            continue
        if path.is_symlink():
            return ""
        if path.is_file() and relative.name not in {"terminal-predictions.csv", "investigation.json"}:
            digest.update(relative.as_posix().encode("ascii") + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _isolation() -> tuple[bool, str]:
    required = [STATE_DIR, ACTIONS, KEY, STATE, TERMINAL, CANDIDATE, HISTORY]
    if not all(path.exists() and not path.is_symlink() for path in required):
        return False, "authoritative_state_missing"
    if STATE_DIR == Path("/var/lib/capital-bike-task"):
        for path in required:
            info = path.stat()
            if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return False, f"authoritative_state_untrusted:{path.name}"
        if KEY.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH):
            return False, "action_key_readable_by_agent"
    try:
        STATE_DIR.relative_to(WORKSPACE)
        return False, "state_inside_workspace"
    except ValueError:
        return True, "ok"


def _binding() -> tuple[bool, str]:
    try:
        terminal = json.loads(TERMINAL.read_text(encoding="ascii"))
        state = json.loads(STATE.read_text(encoding="ascii"))
    except Exception:
        return False, "terminal_metadata_parse"
    if not state.get("submitted") or state.get("phase") != "complete":
        return False, "terminal_not_submitted"
    if terminal.get("candidate_hash") != _bundle_hash(CANDIDATE):
        return False, "terminal_candidate_unbound"
    if terminal.get("history_sha256") != hashlib.sha256(HISTORY.read_bytes()).hexdigest():
        return False, "terminal_history_unbound"
    if terminal.get("runtime_generation") != 2 or terminal.get("immutable") is not True:
        return False, "terminal_generation_invalid"
    return True, "ok"


def _terminal() -> tuple[bool, str, dict[str, Any]]:
    if os.geteuid() != 0:
        return False, "verifier_requires_root", {}
    if not SOURCE_TERMINAL.is_file() or SOURCE_TERMINAL.is_symlink():
        return False, "verifier_data_missing", {}
    try:
        shutil.copyfile(SOURCE_TERMINAL, PRIVATE_TERMINAL)
        os.chown(PRIVATE_TERMINAL, 0, 0)
        os.chmod(PRIVATE_TERMINAL, 0o600)
    except OSError:
        return False, "verifier_data_isolation", {}
    try:
        process = subprocess.run(
            [sys.executable, str(PROBE)],
            cwd="/tmp",
            text=True,
            capture_output=True,
            timeout=720,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "terminal_probe_timeout", {}
    if process.returncode != 0:
        return False, f"terminal_probe_exit:{process.returncode}", {}
    try:
        payload = json.loads(process.stdout.strip().splitlines()[-1])
    except Exception:
        return False, "terminal_probe_protocol", {}
    return bool(payload.get("healthy")), str(payload.get("reason", "unhealthy")), payload


def grade() -> dict[str, Any]:
    actions = _load_actions()
    chain, chain_reason = _chain(actions)
    walk, walk_reason, counts = _walk(actions)
    isolation, isolation_reason = _isolation()
    binding, binding_reason = _binding() if isolation else (False, "state_untrusted")
    terminal, terminal_reason, detail = _terminal() if binding else (False, "terminal_unbound", {})
    strict = bool(chain and walk and isolation and binding and terminal)
    return {
        "reward": 1 if strict else 0,
        "detail": {
            "signed_root_action_chain_ok": chain,
            "chain_reason": chain_reason,
            "causal_gate_walk_ok": walk,
            "gate_reason": walk_reason,
            "service_state_isolated": isolation,
            "isolation_reason": isolation_reason,
            "terminal_binding_ok": binding,
            "binding_reason": binding_reason,
            "terminal_correct": terminal,
            "terminal_reason": terminal_reason,
            "accepted_action_counts": counts,
            "terminal": detail,
        },
    }


def main() -> None:
    try:
        result = grade()
    except Exception as exc:
        result = {"reward": 0, "detail": {"grader_error": type(exc).__name__}}
    REWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REWARD_PATH.write_bytes(str(int(result["reward"])).encode("ascii"))
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    print(f"Final score: {result['reward']}")


if __name__ == "__main__":
    main()
