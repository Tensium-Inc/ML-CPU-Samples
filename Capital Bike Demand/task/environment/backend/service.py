#!/usr/bin/env python3
"""Root-owned gated service for the Capital Bike forecasting incident."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


INSTALLED = Path(__file__).resolve().parent == Path("/opt/task/backend")
WORKSPACE = Path("/workspace/target")
STATE_DIR = Path("/var/lib/capital-bike-task")
PRIVATE_DIR = Path("/opt/task/backend/private")
BASE_HISTORY = PRIVATE_DIR / "base_history.csv"
WAVE1 = PRIVATE_DIR / "validation_wave1.csv"
WAVE2 = PRIVATE_DIR / "validation_wave2.csv"
TERMINAL_REQUESTS = PRIVATE_DIR / "terminal_requests.csv"
SOCKET_PATH = Path("/run/capital-bike-task/ops.sock")
RUN_USER = "ubuntu"

STATE = STATE_DIR / "state.json"
ACTIONS = STATE_DIR / "actions.jsonl"
KEY = STATE_DIR / "action.key"
RUNTIME_HISTORY = STATE_DIR / "runtime_history.csv"
STAGED = STATE_DIR / "staged_candidate"
CANDIDATE = STATE_DIR / "candidate"
TERMINAL_CANDIDATE = STATE_DIR / "terminal_candidate"
TERMINAL_HISTORY = STATE_DIR / "terminal_history.csv"
TERMINAL = STATE_DIR / "terminal.json"
DELIVERABLE = WORKSPACE / "terminal-predictions.csv"

OUTPUT_COLUMNS = (
    "instant",
    "predicted_cnt",
    "lower_80",
    "upper_80",
)
CODE_ROOTS = ("pipeline", "scripts")
VALIDATE_LIMIT = 3
LOCK = threading.Lock()


class ServiceError(RuntimeError):
    pass


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="ascii")
    os.chmod(temp, mode)
    temp.replace(path)


def _safe_files(root: Path):
    if not root.is_dir() or root.is_symlink():
        raise ServiceError("unsafe candidate root")
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in {"__pycache__", "results"}:
            continue
        if "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            raise ServiceError(f"candidate symlink: {relative}")
        if path.is_file():
            yield path, relative


def _copy_file(source: Path, destination: Path) -> None:
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        chunks = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
    finally:
        os.close(descriptor)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"".join(chunks))
    os.chmod(destination, 0o644)


def _write_deliverable(frame: pd.DataFrame) -> None:
    raw = frame.to_csv(index=False, lineterminator="\n", float_format="%.12g").encode("ascii")
    try:
        DELIVERABLE.unlink(missing_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(DELIVERABLE, flags, 0o444)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), 0o444)
    except OSError as exc:
        raise ServiceError("unsafe terminal deliverable") from exc


def _snapshot(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for path, relative in _safe_files(source):
        if relative.name in {"terminal-predictions.csv", "investigation.json"}:
            continue
        _copy_file(path, destination / relative)


def _bundle_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path, relative in _safe_files(root):
        if relative.name in {"terminal-predictions.csv", "investigation.json"}:
            continue
        digest.update(relative.as_posix().encode("ascii") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _code_manifest(root: Path) -> dict[str, str]:
    result = {}
    for name in CODE_ROOTS:
        directory = root / name
        if not directory.is_dir() or directory.is_symlink():
            raise ServiceError(f"missing code directory: {name}")
        for path in sorted(directory.rglob("*.py")):
            if path.is_symlink() or not path.is_file():
                raise ServiceError("unsafe code surface")
            relative = path.relative_to(root).as_posix()
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _code_hash(root: Path) -> str:
    return hashlib.sha256(_json_bytes(_code_manifest(root))).hexdigest()


def _new_state() -> dict[str, Any]:
    manifest = _code_manifest(WORKSPACE)
    return {
        "phase": "inspect.contract",
        "locked": False,
        "chain_hash": "GENESIS",
        "pristine_bundle_hash": _bundle_hash(WORKSPACE),
        "pristine_code_hash": hashlib.sha256(_json_bytes(manifest)).hexdigest(),
        "pristine_manifest": manifest,
        "evidence": {},
        "hypothesis_committed": False,
        "validate_count": 0,
        "fault_injected": False,
        "revision_used": False,
        "cache_recovered": False,
        "cache_audited": False,
        "diagnosed": False,
        "diagnosis_receipt": None,
        "recovery_planned": False,
        "recovery_verified": False,
        "runtime_generation": 0,
        "reproduce_hash": None,
        "reproduce_generation": None,
        "stage_hash": None,
        "prepare_hash": None,
        "candidate_hash": None,
        "candidate_code_hash": None,
        "candidate_manifest": None,
        "clean_validate": False,
        "horizon_audited": False,
        "intervals_audited": False,
        "canary_promoted": False,
        "canary_clean": False,
        "promoted": False,
        "frozen": False,
        "submitted": False,
    }


def initialize() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if INSTALLED:
        os.chown(STATE_DIR, 0, 0)
        os.chmod(STATE_DIR, 0o700)
    if KEY.is_symlink():
        raise ServiceError("unsafe action key")
    if not KEY.exists():
        descriptor = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, os.urandom(32))
        finally:
            os.close(descriptor)
    if not KEY.is_file() or len(KEY.read_bytes()) != 32:
        raise ServiceError("invalid action key")
    os.chmod(KEY, 0o600)
    if not RUNTIME_HISTORY.exists():
        _copy_file(BASE_HISTORY, RUNTIME_HISTORY)
        os.chmod(RUNTIME_HISTORY, 0o600)
    if not STATE.exists():
        _atomic_json(STATE, _new_state())


def _state() -> dict[str, Any]:
    initialize()
    return json.loads(STATE.read_text(encoding="ascii"))


def _save(state: dict[str, Any]) -> None:
    _atomic_json(STATE, state)


def _log(state: dict[str, Any], op: str, accepted: bool, payload: dict[str, Any], op_class: str) -> str:
    body = {
        "seq": int(state.get("sequence", 0)) + 1,
        "ts_ns": time.time_ns(),
        "op": op,
        "op_class": op_class,
        "accepted": bool(accepted),
        "payload": payload,
        "prev": state.get("chain_hash", "GENESIS"),
    }
    body["signature"] = hmac.new(KEY.read_bytes(), _json_bytes(body), hashlib.sha256).hexdigest()
    action_id = hashlib.sha256(_json_bytes(body)).hexdigest()
    state["sequence"] = body["seq"]
    state["chain_hash"] = action_id
    _save(state)
    with ACTIONS.open("a", encoding="ascii") as stream:
        stream.write(json.dumps(body, sort_keys=True, ensure_ascii=True) + "\n")
    os.chmod(ACTIONS, 0o600)
    return action_id


def _response(accepted: bool, op: str, **payload: Any) -> tuple[int, dict[str, Any]]:
    return (0 if accepted else 1), {"accepted": accepted, "op": op, **payload}


def _reject(state: dict[str, Any], op: str, reason: str, *, lock: bool = False) -> tuple[int, dict[str, Any]]:
    if lock:
        state["locked"] = True
        state["phase"] = "locked"
    _log(state, op, False, {"error": reason, "locked": bool(lock)}, "rejected")
    return _response(False, op, error=reason, locked=bool(lock))


def _accept(
    state: dict[str, Any],
    op: str,
    payload: dict[str, Any],
    next_phase: str,
    op_class: str = "operational",
) -> tuple[int, dict[str, Any]]:
    state["phase"] = next_phase
    action_id = _log(state, op, True, payload, op_class)
    return _response(True, op, action_id=action_id, result=payload, next=next_phase)


def _run_identity() -> dict[str, Any]:
    if os.geteuid() == 0:
        try:
            pwd.getpwnam(RUN_USER)
        except KeyError:
            return {}
        return {"user": RUN_USER, "group": RUN_USER}
    return {}


def _chown_run(root: Path) -> None:
    if os.geteuid() != 0:
        return
    try:
        account = pwd.getpwnam(RUN_USER)
    except KeyError:
        return
    for path in [root, *root.rglob("*")]:
        os.chown(path, account.pw_uid, account.pw_gid)


def _run(command: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(cwd),
        "TMPDIR": str(cwd),
        "LANG": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=environment,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        **_run_identity(),
    )


def _last_json(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ServiceError("candidate produced no JSON object")


def _run_workspace(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return _run(command, WORKSPACE, timeout)


def _history_frame() -> pd.DataFrame:
    frame = pd.read_csv(BASE_HISTORY)
    frame["dteday"] = pd.to_datetime(frame["dteday"], errors="raise")
    return frame.sort_values("instant").reset_index(drop=True)


def _wave(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {
        "instant",
        "dteday",
        "hr",
        "workingday",
        "casual",
        "registered",
        "cnt",
    }
    if not required.issubset(frame.columns):
        raise ServiceError(f"private wave missing columns: {path.name}")
    frame["dteday"] = pd.to_datetime(frame["dteday"], errors="raise")
    return frame


def _prediction_metrics(output: pd.DataFrame, labeled: pd.DataFrame) -> tuple[bool, str, dict[str, Any]]:
    if list(output.columns) != list(OUTPUT_COLUMNS):
        return False, "output_schema", {}
    candidate = output.copy()
    for column in OUTPUT_COLUMNS:
        candidate[column] = pd.to_numeric(candidate[column], errors="coerce")
    numeric = candidate.loc[:, OUTPUT_COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        return False, "output_nonfinite", {}
    ids = candidate["instant"].to_numpy(dtype=float)
    if not np.allclose(ids, np.rint(ids), rtol=0.0, atol=0.0):
        return False, "output_identity_type", {}
    candidate["instant"] = np.rint(ids).astype(int)
    if candidate["instant"].duplicated().any():
        return False, "output_duplicate_identity", {}
    if (
        (candidate["predicted_cnt"] < 0.0).any()
        or (candidate["lower_80"] < 0.0).any()
        or (candidate["lower_80"] > candidate["predicted_cnt"]).any()
        or (candidate["predicted_cnt"] > candidate["upper_80"]).any()
    ):
        return False, "output_interval_contract", {}
    actual = labeled.copy()
    actual["instant"] = pd.to_numeric(actual["instant"], errors="raise").astype(int)
    actual["dteday"] = pd.to_datetime(actual["dteday"], errors="raise")
    joined = actual.merge(candidate, on="instant", how="outer", indicator=True)
    if len(joined) != len(actual) or not (joined["_merge"] == "both").all():
        return False, "output_identity_coverage", {"expected": int(len(actual)), "observed": int(len(candidate))}
    error = joined["predicted_cnt"].to_numpy(dtype=float) - joined["cnt"].to_numpy(dtype=float)
    month = joined["dteday"].dt.month.to_numpy(dtype=int)
    month_rmse = {
        str(value): float(np.sqrt(np.mean(np.square(error[month == value]))))
        for value in sorted(set(month.tolist()))
    }
    commute = (
        joined["workingday"].eq(1)
        & joined["hr"].isin([7, 8, 9, 16, 17, 18])
    ).to_numpy()
    lower = joined["lower_80"].to_numpy(dtype=float)
    upper = joined["upper_80"].to_numpy(dtype=float)
    actual_value = joined["cnt"].to_numpy(dtype=float)
    details: dict[str, Any] = {
        "rows": int(len(joined)),
        "rmse": float(np.sqrt(np.mean(np.square(error)))),
        "mae": float(np.mean(np.abs(error))),
        "worst_month_rmse": max(month_rmse.values()),
        "commute_mae": float(np.mean(np.abs(error[commute]))),
        "coverage": float(np.mean((actual_value >= lower) & (actual_value <= upper))),
        "mean_width": float(np.mean(upper - lower)),
    }
    return True, "ok", details


def _execute_candidate(
    source: Path,
    history: pd.DataFrame,
    labeled_requests: pd.DataFrame,
    *,
    shuffle_seed: int | None = None,
) -> tuple[bool, str, dict[str, Any], pd.DataFrame | None]:
    run = Path(tempfile.mkdtemp(prefix="bike-candidate-", dir="/tmp"))
    try:
        _snapshot(source, run)
        data_dir = run / ".runtime"
        data_dir.mkdir()
        history_input = history.copy()
        request_input = labeled_requests.drop(
            columns=[column for column in ("casual", "registered", "cnt") if column in labeled_requests.columns]
        )
        if shuffle_seed is not None:
            history_input = history_input.sample(frac=1.0, random_state=shuffle_seed).reset_index(drop=True)
            request_input = request_input.sample(frac=1.0, random_state=shuffle_seed + 1).reset_index(drop=True)
        history_path = data_dir / "history.csv"
        requests_path = data_dir / "requests.csv"
        output_path = data_dir / "predictions.csv"
        history_input.to_csv(history_path, index=False)
        request_input.to_csv(requests_path, index=False)
        _chown_run(run)
        process = _run(
            [
                sys.executable,
                "scripts/predict.py",
                "--history",
                str(history_path),
                "--requests",
                str(requests_path),
                "--output",
                str(output_path),
            ],
            run,
            timeout=60,
        )
        if process.returncode != 0 or not output_path.is_file():
            detail = (process.stderr or process.stdout or "candidate failed")[-240:]
            return False, "candidate_runtime", {"detail": detail}, None
        try:
            output = pd.read_csv(output_path)
        except Exception as exc:
            return False, "candidate_output_parse", {"detail": type(exc).__name__}, None
        valid, reason, metrics = _prediction_metrics(output, labeled_requests)
        return valid, reason, metrics, output
    except subprocess.TimeoutExpired:
        return False, "candidate_timeout", {}, None
    except Exception as exc:
        return False, "candidate_exception", {"detail": type(exc).__name__}, None
    finally:
        shutil.rmtree(run, ignore_errors=True)


def _within(metrics: dict[str, Any], *, phase: int) -> bool:
    if phase == 1:
        return (
            metrics.get("rmse", math.inf) <= 120.0
            and metrics.get("worst_month_rmse", math.inf) <= 135.0
            and metrics.get("commute_mae", math.inf) <= 180.0
            and 0.30 <= metrics.get("coverage", -math.inf) <= 1.0
            and metrics.get("mean_width", math.inf) <= 400.0
        )
    return (
        metrics.get("rmse", math.inf) <= 110.0
        and metrics.get("worst_month_rmse", math.inf) <= 125.0
        and metrics.get("commute_mae", math.inf) <= 165.0
        and 0.30 <= metrics.get("coverage", -math.inf) <= 1.0
        and metrics.get("mean_width", math.inf) <= 400.0
    )


def _probe_schema() -> dict[str, Any]:
    registry = json.loads((WORKSPACE / "data" / "schema_registry.json").read_text(encoding="ascii"))
    return {
        "export_count": len(registry["exports"]),
        "expected_unique_rows": int(registry["expected_unique_history_rows"]),
        "delimiters": [item["delimiter"] for item in registry["exports"]],
        "renamed_exports": sum(bool(item.get("rename")) for item in registry["exports"]),
        "scaled_exports": sum(bool(item.get("scale_to_canonical")) for item in registry["exports"]),
        "deduplicate_key": "instant",
    }


def _probe_leakage() -> dict[str, Any]:
    frame = _history_frame()
    requests = pd.read_csv(TERMINAL_REQUESTS, nrows=8)
    return {
        "history_outcome_columns": [name for name in ("casual", "registered", "cnt") if name in frame],
        "request_outcome_columns": [name for name in ("casual", "registered", "cnt") if name in requests],
        "request_columns": list(requests.columns),
        "rule": "training outcomes are unavailable at issue time",
    }


def _probe_year_bridge() -> dict[str, Any]:
    frame = _history_frame()
    summary = (
        frame.groupby(["yr", "mnth"], as_index=False)["cnt"]
        .mean()
        .sort_values(["mnth", "yr"])
    )
    paired = []
    for month in range(1, 5):
        old = float(summary[(summary["yr"] == 0) & (summary["mnth"] == month)]["cnt"].iloc[0])
        new = float(summary[(summary["yr"] == 1) & (summary["mnth"] == month)]["cnt"].iloc[0])
        paired.append({"month": month, "year_0_mean": round(old, 3), "year_1_mean": round(new, 3)})
    return {"paired_month_demand": paired, "terminal_year_index": 1, "future_months": [9, 10, 11, 12]}


def _probe_commute() -> dict[str, Any]:
    frame = _history_frame()
    focus = frame[frame["hr"].isin([7, 8, 9, 16, 17, 18])]
    summary = focus.groupby(["yr", "workingday", "hr"])["cnt"].mean().reset_index()
    rows = summary[summary["workingday"] == 1].to_dict("records")
    for row in rows:
        row["cnt"] = round(float(row["cnt"]), 3)
    return {"workingday_commute_profile": rows, "protected_metric": "working-day commute-hour MAE"}


def _probe_horizon() -> dict[str, Any]:
    frame = _history_frame()
    requests = pd.read_csv(TERMINAL_REQUESTS)
    return {
        "history_start": str(frame["dteday"].min().date()),
        "history_end": str(frame["dteday"].max().date()),
        "terminal_start": str(pd.to_datetime(requests["dteday"]).min().date()),
        "terminal_end": str(pd.to_datetime(requests["dteday"]).max().date()),
        "terminal_rows": int(len(requests)),
        "terminal_months": sorted(pd.to_datetime(requests["dteday"]).dt.month.unique().astype(int).tolist()),
        "same_hour_weather_available": True,
    }


def _investigation_identity(state: dict[str, Any]) -> tuple[bool, str, str]:
    code = _code_hash(WORKSPACE)
    return (
        code == state["pristine_code_hash"],
        state["pristine_bundle_hash"],
        state["pristine_code_hash"],
    )


def _handle_investigation(state: dict[str, Any], op: str, args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    unchanged, bundle_hash, code_hash = _investigation_identity(state)
    if not unchanged:
        return _reject(state, op, "implementation_changed_before_hypothesis", lock=True)
    if op == "inspect.contract":
        payload = {
            "candidate_hash": bundle_hash,
            "code_hash": code_hash,
            "output_columns": list(OUTPUT_COLUMNS),
            "terminal_bars": {
                "overall_rmse_max": 65.0,
                "month_rmse_max": 72.0,
                "commute_mae_max": 76.0,
                "coverage_min": 0.70,
                "coverage_max": 0.98,
                "mean_width_max": 250.0,
            },
            "validate_limit": VALIDATE_LIMIT,
        }
        return _accept(state, op, payload, "inspect.exports", "investigation")
    if op == "inspect.exports":
        registry = json.loads((WORKSPACE / "data" / "schema_registry.json").read_text(encoding="ascii"))
        payload = {
            "candidate_hash": bundle_hash,
            "code_hash": code_hash,
            "exports": [item["file"] for item in registry["exports"]],
            "expected_unique_rows": int(registry["expected_unique_history_rows"]),
            "history_start": registry["history_start"],
            "history_end": registry["history_end"],
        }
        return _accept(state, op, payload, "profile.current", "investigation")
    if op == "profile.current":
        process = _run_workspace([sys.executable, "scripts/run_backtest.py"], 180)
        if process.returncode != 0:
            return _reject(state, op, "public_profile_failed")
        report = _last_json(process.stdout)
        payload = {"candidate_hash": bundle_hash, "code_hash": code_hash, "public_rehearsal": report}
        return _accept(state, op, payload, "probe.schema", "investigation")
    probes = {
        "probe.schema": (_probe_schema, "probe.leakage"),
        "probe.leakage": (_probe_leakage, "probe.year_bridge"),
        "probe.year_bridge": (_probe_year_bridge, "probe.commute"),
        "probe.commute": (_probe_commute, "probe.horizon"),
        "probe.horizon": (_probe_horizon, "hypothesis.commit"),
    }
    if op in probes:
        function, next_phase = probes[op]
        measured = function()
        payload = {"candidate_hash": bundle_hash, "code_hash": code_hash, **measured}
        action_id = _log(state, op, True, payload, "investigation")
        evidence_id = f"ev-{action_id[:16]}"
        state["evidence"][evidence_id] = op
        state["phase"] = next_phase
        _save(state)
        return _response(True, op, action_id=action_id, result={"evidence_id": evidence_id, **payload}, next=next_phase)
    if op == "hypothesis.commit":
        cited = list(dict.fromkeys(args.evidence or []))
        known = state.get("evidence", {})
        if len(cited) != 5 or set(cited) != set(known):
            return _reject(state, op, "five_probe_evidence_ids_required")
        summary_path = (WORKSPACE / args.summary_file).resolve()
        try:
            summary_path.relative_to(WORKSPACE)
        except ValueError:
            return _reject(state, op, "summary_outside_workspace")
        try:
            raw = summary_path.read_bytes()
            if not 160 <= len(raw) <= 8192 or any(byte > 127 for byte in raw):
                raise ValueError("summary size or encoding")
            summary = json.loads(raw.decode("ascii"))
        except Exception:
            return _reject(state, op, "summary_invalid")
        if summary.get("candidate_hash") != bundle_hash or summary.get("code_hash") != code_hash:
            return _reject(state, op, "summary_candidate_mismatch")
        entries = summary.get("evidence")
        if not isinstance(entries, list) or {entry.get("id") for entry in entries if isinstance(entry, dict)} != set(cited):
            return _reject(state, op, "summary_evidence_mismatch")
        for entry in entries:
            observation = entry.get("observation")
            if not isinstance(observation, str) or not 20 <= len(observation.strip()) <= 500:
                return _reject(state, op, "summary_observation_invalid")
        hypothesis = summary.get("hypothesis")
        planned = summary.get("planned_test")
        if not isinstance(hypothesis, str) or not 40 <= len(hypothesis.strip()) <= 1000:
            return _reject(state, op, "summary_hypothesis_invalid")
        if not isinstance(planned, str) or not 20 <= len(planned.strip()) <= 500:
            return _reject(state, op, "summary_planned_test_invalid")
        state["hypothesis_committed"] = True
        payload = {
            "candidate_hash": bundle_hash,
            "code_hash": code_hash,
            "evidence_ids": cited,
            "summary_sha256": hashlib.sha256(raw).hexdigest(),
        }
        return _accept(state, op, payload, "test.visible", "investigation")
    return _reject(state, op, "unknown_investigation_operation")


def _changed_files(state: dict[str, Any]) -> list[str]:
    current = _code_manifest(WORKSPACE)
    pristine = state["pristine_manifest"]
    return sorted(name for name in set(current) | set(pristine) if current.get(name) != pristine.get(name))


def _manifest_changes(current: dict[str, str], previous: dict[str, str]) -> list[str]:
    return sorted(name for name in set(current) | set(previous) if current.get(name) != previous.get(name))


def _public_replay() -> tuple[bool, str, str]:
    frame = _history_frame()
    history = frame[frame["dteday"] < "2012-03-01"].copy()
    requests = frame[(frame["dteday"] >= "2012-03-01") & (frame["dteday"] < "2012-05-01")].copy()
    valid, reason, _, output = _execute_candidate(WORKSPACE, history, requests, shuffle_seed=719)
    if not valid or output is None:
        return False, reason, ""
    normalized = output.sort_values("instant").to_csv(index=False, float_format="%.9g")
    return True, "ok", hashlib.sha256(normalized.encode("ascii")).hexdigest()


def _append_wave_to_cache(path: Path) -> None:
    current = pd.read_csv(RUNTIME_HISTORY)
    wave = _wave(path)
    wave["dteday"] = pd.to_datetime(wave["dteday"], errors="raise").dt.strftime("%Y-%m-%d")
    combined = pd.concat([current, wave], ignore_index=True).sort_values("instant")
    if combined["instant"].duplicated().any():
        raise ServiceError("runtime cache duplicate identity")
    combined.to_csv(RUNTIME_HISTORY, index=False)
    os.chmod(RUNTIME_HISTORY, 0o600)


def _handle_release(state: dict[str, Any], op: str, args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    if op == "candidate.revise":
        if state.get("revision_used"):
            return _reject(state, op, "candidate_revision_already_used")
        current_manifest = _code_manifest(WORKSPACE)
        deployed_manifest = state.get("candidate_manifest") or {}
        changed = _manifest_changes(current_manifest, deployed_manifest)
        current_code_hash = hashlib.sha256(_json_bytes(current_manifest)).hexdigest()
        if len(changed) < 2:
            return _reject(state, op, "multi_file_revision_required")
        if current_code_hash == state.get("candidate_code_hash"):
            return _reject(state, op, "candidate_revision_not_detected")
        state["revision_used"] = True
        payload = {
            "changed_files": changed,
            "changed_count": len(changed),
            "code_hash": current_code_hash,
            "revision": 1,
        }
        return _accept(state, op, payload, "test.visible")
    if op == "test.visible":
        process = _run_workspace([sys.executable, "-m", "unittest", "discover", "-s", "tests"], 180)
        if process.returncode != 0:
            return _reject(state, op, "visible_tests_failed")
        return _accept(state, op, {"passed": True}, "backtest.replay")
    if op == "backtest.replay":
        process = _run_workspace([sys.executable, "scripts/run_backtest.py"], 180)
        if process.returncode != 0:
            return _reject(state, op, "public_backtest_failed")
        return _accept(state, op, {"report": _last_json(process.stdout)}, "candidate.attest")
    if op == "candidate.attest":
        changed = _changed_files(state)
        if len(changed) < 2:
            return _reject(state, op, "multi_file_change_required")
        payload = {"changed_files": changed, "changed_count": len(changed), "code_hash": _code_hash(WORKSPACE)}
        return _accept(state, op, payload, "reproduce")
    if op == "reproduce":
        ok, reason, output_hash = _public_replay()
        if not ok:
            return _reject(state, op, f"public_replay_failed:{reason}")
        state["reproduce_hash"] = _bundle_hash(WORKSPACE)
        state["reproduce_generation"] = int(state["runtime_generation"])
        payload = {
            "candidate_hash": state["reproduce_hash"],
            "runtime_generation": state["reproduce_generation"],
            "output_sha256": output_hash,
        }
        return _accept(state, op, payload, "stage.open")
    if op == "stage.open":
        current = _bundle_hash(WORKSPACE)
        if current != state.get("reproduce_hash") or int(state["runtime_generation"]) != state.get("reproduce_generation"):
            return _reject(state, op, "reproduce_binding_changed")
        _snapshot(WORKSPACE, STAGED)
        state["stage_hash"] = _bundle_hash(STAGED)
        payload = {"candidate_hash": state["stage_hash"], "runtime_generation": state["runtime_generation"]}
        return _accept(state, op, payload, "deploy.prepare")
    if op == "deploy.prepare":
        if not STAGED.is_dir() or _bundle_hash(STAGED) != state.get("stage_hash"):
            return _reject(state, op, "stage_binding_invalid")
        state["prepare_hash"] = state["stage_hash"]
        payload = {
            "candidate_hash": state["prepare_hash"],
            "runtime_generation": state["runtime_generation"],
            "immutable_stage": True,
        }
        return _accept(state, op, payload, "deploy.commit")
    if op == "deploy.commit":
        if state.get("prepare_hash") != state.get("stage_hash") or _bundle_hash(STAGED) != state.get("stage_hash"):
            return _reject(state, op, "prepared_stage_binding_invalid")
        _snapshot(STAGED, CANDIDATE)
        state["candidate_hash"] = _bundle_hash(CANDIDATE)
        state["candidate_code_hash"] = _code_hash(CANDIDATE)
        state["candidate_manifest"] = _code_manifest(CANDIDATE)
        state["clean_validate"] = False
        payload = {"candidate_hash": state["candidate_hash"], "runtime_generation": state["runtime_generation"]}
        return _accept(state, op, payload, "validate")
    if op == "validate":
        if int(state["validate_count"]) >= VALIDATE_LIMIT:
            return _reject(state, op, "validation_budget_exhausted", lock=True)
        state["validate_count"] = int(state["validate_count"]) + 1
        remaining = VALIDATE_LIMIT - int(state["validate_count"])
        if not state["fault_injected"]:
            state["fault_injected"] = True
            payload = {
                "status": "dirty",
                "remaining": remaining,
                "candidate_hash": state["candidate_hash"],
                "signal": "runtime_snapshot_stale",
            }
            return _accept(state, op, payload, "diagnostics.read")
        phase = 2 if state["cache_recovered"] else 1
        wave = _wave(WAVE2 if phase == 2 else WAVE1)
        history = pd.read_csv(RUNTIME_HISTORY)
        valid, reason, metrics, _ = _execute_candidate(CANDIDATE, history, wave)
        behavior_ok = valid and _within(metrics, phase=phase)
        state["last_private_reason"] = reason
        state["last_private_metrics"] = metrics
        if not behavior_ok:
            if state["cache_recovered"] and not state["revision_used"] and remaining > 0:
                payload = {
                    "status": "dirty",
                    "remaining": remaining,
                    "candidate_hash": state["candidate_hash"],
                    "signal": "protected_behavior_dirty",
                }
                return _accept(state, op, payload, "candidate.revise")
            return _reject(state, op, f"protected_behavior_dirty:{reason}", lock=True)
        state["clean_validate"] = True
        payload = {"status": "clean", "remaining": remaining, "candidate_hash": state["candidate_hash"]}
        return _accept(state, op, payload, "audit.horizon")
    if op == "diagnostics.read":
        if not state["fault_injected"] or state["cache_recovered"]:
            return _reject(state, op, "recoverable_incident_required")
        cache = pd.read_csv(RUNTIME_HISTORY)
        wave = _wave(WAVE1)
        evidence = {
            "runtime_generation": state["runtime_generation"],
            "cache_rows": int(len(cache)),
            "cache_max_instant": int(cache["instant"].max()),
            "validated_wave_rows": int(len(wave)),
            "validated_wave_min_instant": int(wave["instant"].min()),
            "validated_ids_present_in_cache": 0,
            "cache_advance_expected": True,
        }
        state["diagnosed"] = True
        receipt_seed = {
            "chain_hash": state["chain_hash"],
            "next_sequence": int(state.get("sequence", 0)) + 1,
            "evidence": evidence,
        }
        receipt = "diag-" + hmac.new(KEY.read_bytes(), _json_bytes(receipt_seed), hashlib.sha256).hexdigest()[:20]
        payload = {
            "diagnosis_receipt": receipt,
            "evidence": evidence,
            "required_family": "rebuild",
            "choices": ["rebuild", "reload", "restart", "rollback"],
        }
        state["phase"] = "recovery.plan"
        action_id = _log(state, op, True, payload, "recovery")
        state["diagnosis_receipt"] = receipt
        _save(state)
        return _response(True, op, action_id=action_id, result=payload, next="recovery.plan")
    if op == "recovery.plan":
        if not state.get("diagnosed") or args.diagnosis != state.get("diagnosis_receipt"):
            return _reject(state, op, "matching_diagnosis_receipt_required")
        if args.family != "rebuild":
            return _reject(state, op, "wrong_recovery_family")
        state["recovery_planned"] = True
        payload = {"family": args.family, "diagnosis_receipt": args.diagnosis, "status": "planned"}
        return _accept(state, op, payload, "recovery.apply", "recovery")
    if op == "recovery.apply":
        if not state.get("recovery_planned") or args.diagnosis != state.get("diagnosis_receipt"):
            return _reject(state, op, "matching_recovery_plan_required")
        if args.family != "rebuild":
            return _reject(state, op, "wrong_recovery_family")
        _append_wave_to_cache(WAVE1)
        state["cache_recovered"] = True
        state["runtime_generation"] = 1
        payload = {
            "family": args.family,
            "diagnosis_receipt": args.diagnosis,
            "status": "applied",
            "runtime_generation": 1,
        }
        return _accept(state, op, payload, "recovery.verify", "recovery")
    if op == "recovery.verify":
        if not state["cache_recovered"] or int(state["runtime_generation"]) != 1:
            return _reject(state, op, "applied_recovery_required", lock=True)
        cache = pd.read_csv(RUNTIME_HISTORY)
        wave = _wave(WAVE1)
        present = set(wave["instant"].astype(int)).issubset(set(cache["instant"].astype(int)))
        if not present:
            return _reject(state, op, "recovery_did_not_advance_cache", lock=True)
        state["recovery_verified"] = True
        payload = {"status": "verified", "runtime_generation": 1, "cache_rows": int(len(cache))}
        return _accept(state, op, payload, "cache.audit", "recovery")
    if op == "cache.audit":
        cache = pd.read_csv(RUNTIME_HISTORY)
        expected = pd.concat([_history_frame(), _wave(WAVE1)], ignore_index=True)
        actual_keys = cache["instant"].astype(int).sort_values().reset_index(drop=True)
        expected_keys = expected["instant"].astype(int).sort_values().reset_index(drop=True)
        if not actual_keys.equals(expected_keys) or actual_keys.duplicated().any():
            return _reject(state, op, "runtime_cache_identity_mismatch", lock=True)
        state["cache_audited"] = True
        payload = {"runtime_generation": 1, "rows": int(len(cache)), "unique_ids": int(len(actual_keys))}
        return _accept(state, op, payload, "reproduce")
    if op == "audit.horizon":
        if not state["clean_validate"] or not state["cache_audited"]:
            return _reject(state, op, "clean_recovered_candidate_required")
        history = pd.read_csv(RUNTIME_HISTORY)
        wave = _wave(WAVE2)
        first_ok, first_reason, first_metrics, first = _execute_candidate(CANDIDATE, history, wave)
        second_ok, second_reason, second_metrics, second = _execute_candidate(CANDIDATE, history, wave, shuffle_seed=2026)
        if not first_ok or not second_ok or first is None or second is None:
            return _reject(state, op, f"release_replay_failed:{first_reason}:{second_reason}")
        left = first.sort_values("instant").reset_index(drop=True)
        right = second.sort_values("instant").reset_index(drop=True)
        invariant = (
            left[["instant"]].equals(right[["instant"]])
            and np.allclose(left.iloc[:, 1:], right.iloc[:, 1:], rtol=1e-8, atol=1e-8)
        )
        if not invariant or not _within(first_metrics, phase=2) or not _within(second_metrics, phase=2):
            return _reject(state, op, "release_replay_not_invariant")
        state["horizon_audited"] = True
        state["audit_metrics"] = first_metrics
        payload = {"row_order_invariant": True, "candidate_hash": state["candidate_hash"]}
        return _accept(state, op, payload, "audit.intervals")
    if op == "audit.intervals":
        if not state["horizon_audited"]:
            return _reject(state, op, "horizon_audit_required")
        metrics = state.get("audit_metrics", {})
        if not (0.30 <= metrics.get("coverage", -math.inf) <= 1.0 and metrics.get("mean_width", math.inf) <= 400.0):
            return _reject(state, op, "protected_interval_audit_dirty")
        _append_wave_to_cache(WAVE2)
        state["runtime_generation"] = 2
        state["intervals_audited"] = True
        payload = {
            "status": "clean",
            "coverage_band_checked": True,
            "width_checked": True,
            "runtime_generation": 2,
        }
        return _accept(state, op, payload, "promote.canary")
    if op == "promote.canary":
        if int(state["runtime_generation"]) != 2 or not state["intervals_audited"]:
            return _reject(state, op, "protected_audits_required")
        state["canary_promoted"] = True
        payload = {"candidate_hash": state["candidate_hash"], "traffic_percent": 10}
        return _accept(state, op, payload, "validate.canary")
    if op == "validate.canary":
        if not state["canary_promoted"]:
            return _reject(state, op, "canary_promotion_required")
        history = pd.read_csv(RUNTIME_HISTORY)
        wave = _wave(WAVE2).sample(frac=0.25, random_state=808).reset_index(drop=True)
        valid, reason, metrics, _ = _execute_candidate(CANDIDATE, history, wave, shuffle_seed=809)
        if not valid or not _within(metrics, phase=2):
            return _reject(state, op, f"canary_dirty:{reason}", lock=True)
        state["canary_clean"] = True
        payload = {"status": "clean", "rows": int(len(wave)), "candidate_hash": state["candidate_hash"]}
        return _accept(state, op, payload, "promote.production")
    if op == "promote.production":
        if not state["canary_clean"]:
            return _reject(state, op, "clean_canary_required")
        _snapshot(CANDIDATE, TERMINAL_CANDIDATE)
        terminal_hash = _bundle_hash(TERMINAL_CANDIDATE)
        if terminal_hash != state["candidate_hash"]:
            return _reject(state, op, "promotion_binding_mismatch")
        state["promoted"] = True
        return _accept(state, op, {"candidate_hash": terminal_hash}, "freeze")
    if op == "freeze":
        if not state["promoted"]:
            return _reject(state, op, "promotion_required")
        _copy_file(RUNTIME_HISTORY, TERMINAL_HISTORY)
        os.chmod(TERMINAL_HISTORY, 0o600)
        terminal = {
            "candidate_hash": _bundle_hash(TERMINAL_CANDIDATE),
            "history_sha256": hashlib.sha256(TERMINAL_HISTORY.read_bytes()).hexdigest(),
            "runtime_generation": state["runtime_generation"],
            "immutable": True,
        }
        _atomic_json(TERMINAL, terminal)
        state["frozen"] = True
        return _accept(state, op, terminal, "submit")
    if op == "submit":
        if not state["frozen"] or not TERMINAL.is_file():
            return _reject(state, op, "frozen_terminal_required")
        history = pd.read_csv(TERMINAL_HISTORY)
        requests = pd.read_csv(TERMINAL_REQUESTS)
        labeled_contract = requests.copy()
        labeled_contract["cnt"] = 0.0
        labeled_contract["casual"] = 0.0
        labeled_contract["registered"] = 0.0
        valid, reason, _, output = _execute_candidate(
            TERMINAL_CANDIDATE,
            history,
            labeled_contract,
            shuffle_seed=404,
        )
        if not valid or output is None:
            return _reject(state, op, f"terminal_delivery_failed:{reason}")
        output = output.sort_values("instant").reset_index(drop=True)
        _write_deliverable(output)
        payload = {"rows": int(len(output)), "output": DELIVERABLE.name}
        state["submitted"] = True
        accepted = _accept(state, op, payload, "complete")
        return accepted
    return _reject(state, op, "unknown_release_operation")


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("op")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--summary-file", default="investigation.json")
    parser.add_argument("--family", default="")
    parser.add_argument("--diagnosis", default="")
    return parser.parse_args(argv)


def dispatch(argv: list[str]) -> tuple[int, dict[str, Any]]:
    try:
        args = _parse(argv)
    except SystemExit:
        return 2, {"accepted": False, "error": "invalid_arguments"}
    op = args.op
    with LOCK:
        try:
            state = _state()
            if state.get("locked"):
                return _reject(state, op, "incident_locked")
            if state.get("phase") == "complete":
                return _reject(state, op, "terminal_already_submitted")
            if op != state.get("phase"):
                return _reject(state, op, f"out_of_order:expected:{state.get('phase')}")
            if not state["hypothesis_committed"]:
                return _handle_investigation(state, op, args)
            return _handle_release(state, op, args)
        except ServiceError as exc:
            state = _state()
            return _reject(state, op, str(exc))
        except Exception as exc:
            state = _state()
            return _reject(state, op, f"service_error:{type(exc).__name__}")


def _serve() -> None:
    initialize()
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists() or SOCKET_PATH.is_symlink():
        SOCKET_PATH.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_PATH))
    os.chmod(SOCKET_PATH, 0o666)
    server.listen(16)
    while True:
        connection, _ = server.accept()
        with connection:
            try:
                raw = connection.recv(65536)
                request = json.loads(raw.splitlines()[0].decode("ascii"))
                code, payload = dispatch(list(request.get("argv", [])))
            except Exception as exc:
                code, payload = 2, {"accepted": False, "error": f"request_error:{type(exc).__name__}"}
            reply = {"returncode": code, "payload": payload}
            connection.sendall(_json_bytes(reply) + b"\n")


def main() -> int:
    if sys.argv[1:] == ["--initialize"]:
        initialize()
        return 0
    if sys.argv[1:] == ["--serve"]:
        _serve()
        return 0
    code, payload = dispatch(sys.argv[1:])
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
