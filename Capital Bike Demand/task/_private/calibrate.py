#!/usr/bin/env python3
"""Free model-independent calibration for positive and negative controls."""
from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
WORKSPACE = TASK / "environment" / "workspace"
BACKEND = TASK / "environment" / "backend" / "service.py"
PRIVATE = TASK / "environment" / "backend" / "private"
TESTS = TASK / "tests"
GRADE = TESTS / "grade.py"
PROBE = TESTS / "terminal_probe.py"
EXPECTED = json.loads((HERE / "negative_controls" / "expected.json").read_text(encoding="ascii"))


SCENARIOS = {
    "gold": TASK / "solution" / "solve.sh",
    "alt": TASK / "solution" / "alt_solve.sh",
    "alt2": TASK / "solution" / "alt2_solve.sh",
    "revision": HERE / "revision_control.sh",
}
for path in sorted((HERE / "negative_controls").glob("nc_*.sh")):
    SCENARIOS[path.stem] = path


def independent_solutions() -> tuple[bool, dict[str, float]]:
    names = ["hgb_engine.py", "rf_engine.py", "et_engine.py"]
    sources = {
        name: [line.strip() for line in (TASK / "solution" / name).read_text(encoding="ascii").splitlines() if line.strip()]
        for name in names
    }
    ratios = {}
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            ratios[f"{left}:{right}"] = round(SequenceMatcher(None, sources[left], sources[right]).ratio(), 6)
    return all(value < 0.90 for value in ratios.values()), ratios


def environment(root: Path) -> dict[str, str]:
    values = os.environ.copy()
    values.update(
        {
            "WORKSPACE_DIR": str(root / "target"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return values


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="ascii")
    if text.count(old) != 1:
        raise RuntimeError(f"calibration patch target changed: {path.name}: {old}")
    path.write_text(text.replace(old, new), encoding="ascii")


def materialize_runtime(root: Path) -> subprocess.Popen[str]:
    shutil.copytree(WORKSPACE, root / "target")
    shutil.copy2(BACKEND, root / "service.py")
    verifier = root / "verifier"
    verifier.mkdir()
    shutil.copy2(GRADE, verifier / "grade.py")
    shutil.copy2(PROBE, verifier / "terminal_probe.py")
    shutil.copy2(TESTS / "terminal.csv", verifier / "terminal.csv")

    workspace = root / "target"
    state = root / "state"
    socket_path = root / "ops.sock"
    reward = root / "reward.txt"
    run_user = pwd.getpwuid(os.getuid()).pw_name

    service = root / "service.py"
    replace_once(service, 'WORKSPACE = Path("/workspace/target")', f"WORKSPACE = Path({str(workspace)!r})")
    replace_once(service, 'STATE_DIR = Path("/var/lib/capital-bike-task")', f"STATE_DIR = Path({str(state)!r})")
    replace_once(service, 'PRIVATE_DIR = Path("/opt/task/backend/private")', f"PRIVATE_DIR = Path({str(PRIVATE)!r})")
    replace_once(service, 'SOCKET_PATH = Path("/run/capital-bike-task/ops.sock")', f"SOCKET_PATH = Path({str(socket_path)!r})")
    replace_once(service, 'RUN_USER = "ubuntu"', f"RUN_USER = {run_user!r}")

    client = workspace / "env_cli.py"
    replace_once(client, 'SOCKET_PATH = Path("/run/capital-bike-task/ops.sock")', f"SOCKET_PATH = Path({str(socket_path)!r})")

    grader = verifier / "grade.py"
    replace_once(grader, 'WORKSPACE = Path("/workspace/target")', f"WORKSPACE = Path({str(workspace)!r})")
    replace_once(grader, 'STATE_DIR = Path("/var/lib/capital-bike-task")', f"STATE_DIR = Path({str(state)!r})")
    replace_once(grader, 'REWARD_PATH = Path("/logs/verifier/reward.txt")', f"REWARD_PATH = Path({str(reward)!r})")
    replace_once(
        grader,
        'if os.geteuid() != 0:\n        return False, "verifier_requires_root", {}',
        'if False:\n        return False, "verifier_requires_root", {}',
    )
    replace_once(
        grader,
        "os.chown(PRIVATE_TERMINAL, 0, 0)",
        "os.chown(PRIVATE_TERMINAL, os.getuid(), os.getgid())",
    )

    probe = verifier / "terminal_probe.py"
    replace_once(probe, 'STATE_DIR = Path("/var/lib/capital-bike-task")', f"STATE_DIR = Path({str(state)!r})")
    replace_once(
        probe,
        'DELIVERABLE = Path("/workspace/target/terminal-predictions.csv")',
        f"DELIVERABLE = Path({str(workspace / 'terminal-predictions.csv')!r})",
    )
    replace_once(probe, 'RUN_USER = "ubuntu"', f"RUN_USER = {run_user!r}")

    process = subprocess.Popen(
        [sys.executable, str(service), "--serve"],
        cwd=str(root),
        env=environment(root),
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 10.0
    while time.time() < deadline and not socket_path.is_socket() and process.poll() is None:
        time.sleep(0.05)
    if not socket_path.is_socket():
        error = process.stderr.read() if process.stderr else ""
        process.terminate()
        raise RuntimeError(f"calibration service failed: {error[-500:]}")
    return process


def grade(root: Path, env: dict[str, str]) -> tuple[int, str, bool]:
    process = subprocess.run(
        [sys.executable, str(root / "verifier" / "grade.py")],
        cwd=str(root / "target"),
        env=env,
        text=True,
        capture_output=True,
        timeout=360,
        check=False,
    )
    reward_path = root / "reward.txt"
    try:
        raw = reward_path.read_bytes()
        reward = int(raw.decode("ascii")) if raw in {b"0", b"1"} else -1
    except Exception:
        reward = -1
    reason = ""
    for line in process.stdout.splitlines():
        if '"terminal_reason"' in line or '"gate_reason"' in line or '"binding_reason"' in line:
            reason = line.strip().rstrip(",")
    clean = process.returncode == 0 and "Traceback" not in process.stdout + process.stderr
    return reward, reason, clean


def run_scenario(name: str, driver: Path, keep: bool = False) -> tuple[int, str, bool, Path | None]:
    root = Path(tempfile.mkdtemp(prefix=f"capital-bike-{name}-", dir="/tmp")).resolve()
    service = materialize_runtime(root)
    env = environment(root)
    try:
        process = subprocess.run(
            ["bash", str(driver)],
            cwd=str(root / "target"),
            env=env,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
        reward, reason, clean = grade(root, env)
    finally:
        service.terminate()
        try:
            service.wait(timeout=5)
        except subprocess.TimeoutExpired:
            service.kill()
            service.wait(timeout=5)
    if not reason:
        reason = f"driver_exit:{process.returncode}"
    if keep:
        return reward, reason, clean, root
    shutil.rmtree(root, ignore_errors=True)
    return reward, reason, clean, None


def malformed_deliverables(root: Path) -> list[tuple[str, int, bool]]:
    env = environment(root)
    deliverable = root / "target" / "terminal-predictions.csv"
    original = deliverable.read_bytes()
    cases: list[tuple[str, bytes | None]] = [
        ("empty", b""),
        ("truncated", original[: max(1, len(original) // 3)]),
        ("oversized", b"x" * 10_000_001),
        ("bad_bytes", b"\xff\xfe\x00"),
        ("wrong_name", None),
    ]
    results = []
    for name, payload in cases:
        deliverable.chmod(0o600)
        deliverable.write_bytes(original)
        wrong = deliverable.with_name("not-terminal-predictions.csv")
        if wrong.exists():
            wrong.unlink()
        if payload is None:
            deliverable.replace(wrong)
        else:
            deliverable.write_bytes(payload)
        reward, _, clean = grade(root, env)
        results.append((name, reward, clean))
        if wrong.exists():
            wrong.replace(deliverable)
    deliverable.chmod(0o600)
    deliverable.write_bytes(original)
    deliverable.chmod(0o444)
    return results


def perturbed_deliverables(root: Path) -> list[tuple[str, int, bool]]:
    env = environment(root)
    deliverable = root / "target" / "terminal-predictions.csv"
    original = deliverable.read_bytes()
    frame = pd.read_csv(deliverable)
    jittered = frame.copy()
    jittered["predicted_cnt"] += 0.0000001
    jittered["lower_80"] += 0.0000001
    jittered["upper_80"] += 0.0000001
    cases = [
        ("row_order", frame.iloc[::-1], None),
        ("numeric_format", frame, "%.6f"),
        ("in_tolerance_jitter", jittered, "%.9g"),
    ]
    results = []
    for name, variant, float_format in cases:
        deliverable.chmod(0o600)
        variant.to_csv(deliverable, index=False, lineterminator="\n", float_format=float_format)
        reward, _, clean = grade(root, env)
        results.append((name, reward, clean))
    deliverable.chmod(0o600)
    deliverable.write_bytes(original)
    deliverable.chmod(0o444)
    return results


def main() -> int:
    rows = []
    independent_ok, ratios = independent_solutions()
    scenario_contract = set(SCENARIOS) == set(EXPECTED)
    all_ok = independent_ok and scenario_contract
    print(f"solution_independence={'PASS' if independent_ok else 'FAIL'} ratios={json.dumps(ratios, sort_keys=True)}")
    print(f"scenario_contract={'PASS' if scenario_contract else 'FAIL'}")
    print(f"{'scenario':28s} {'score':>5s} {'want':>5s}  result")
    print("-" * 78)
    for name, driver in SCENARIOS.items():
        config = EXPECTED[name]
        if config.get("docker_only"):
            print(f"{name:28s} {'skip':>5s} {config['expect']:>5d}  docker-only isolation control")
            continue
        reward, reason, clean, _ = run_scenario(name, driver)
        ok = reward == config["expect"] and clean
        all_ok = all_ok and ok
        rows.append((name, reward))
        print(f"{name:28s} {reward:5d} {config['expect']:5d}  {'PASS' if ok else 'FAIL'} {reason}")

    for name in ("gold", "nc_do_nothing"):
        expected = EXPECTED[name]["expect"]
        reward, reason, clean, _ = run_scenario(name + "_repeat", SCENARIOS[name])
        ok = reward == expected and clean
        all_ok = all_ok and ok
        print(f"{name + '_repeat':28s} {reward:5d} {expected:5d}  {'PASS' if ok else 'FAIL'} {reason}")

    reward, reason, clean, root = run_scenario("malformed_base", SCENARIOS["gold"], keep=True)
    base_ok = reward == 1 and clean and root is not None
    all_ok = all_ok and base_ok
    print(f"{'malformed_base':28s} {reward:5d} {1:5d}  {'PASS' if base_ok else 'FAIL'} {reason}")
    if root is not None:
        for name, malformed_reward, malformed_clean in malformed_deliverables(root):
            ok = malformed_reward == 0 and malformed_clean
            all_ok = all_ok and ok
            print(f"{'malformed_' + name:28s} {malformed_reward:5d} {0:5d}  {'PASS' if ok else 'FAIL'}")
        for name, perturbed_reward, perturbed_clean in perturbed_deliverables(root):
            ok = perturbed_reward == 1 and perturbed_clean
            all_ok = all_ok and ok
            print(f"{'perturbed_' + name:28s} {perturbed_reward:5d} {1:5d}  {'PASS' if ok else 'FAIL'}")
        shutil.rmtree(root, ignore_errors=True)

    print(f"CALIBRATION {'GREEN' if all_ok else 'RED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
