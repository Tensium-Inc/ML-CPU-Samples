#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devenv import DevEnv                                          # noqa: E402

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
GRADE = TASK / "tests" / "grade.py"
NC = HERE / "negative_controls"
SOLUTION = TASK / "solution"


def scenarios() -> Dict[str, Path]:
    found = {"oracle": SOLUTION / "solve.sh",
             "alt_solve": SOLUTION / "alt_solve.sh",
             "alt2_solve": SOLUTION / "alt2_solve.sh"}
    for path in sorted(NC.glob("nc_*.sh")):
        found[path.stem] = path
    return found


def run_one(name: str, driver: Path) -> Dict[str, Any]:
    started = time.time()
    env_box = DevEnv().start()
    try:
        base = os.environ.copy()
        base.update({
            "WORKSPACE_DIR": str(env_box.workspace),
            "ENVD_SOCK": str(env_box.sock),
            "ENVD_STATE": str(env_box.state),
            "ENVD_DEV": "1",
            "ENVD_PATH": str(TASK / "environment" / "envd" / "envd.py"),
            "ENVD_HIDDEN": str(TASK / "environment" / "hidden"),
            "TERMINAL_HIDDEN": str(TASK / "environment" / "hidden"),
            "PROBE_IMPL": str(TASK / "environment" / "probe" / "terminal_probe.py"),
            "PYTHON": sys.executable,
            "REWARD_PATH": str(env_box.root / "reward.txt"),
        })
        drive = subprocess.run(["bash", str(driver)], env=base, cwd=str(env_box.workspace),
                               capture_output=True, text=True, timeout=3600)
        graded = subprocess.run([sys.executable, str(GRADE)], env=base, cwd=str(TASK),
                                capture_output=True, text=True, timeout=3600)
        # The reward is whatever the harness would read: the FILE, not stdout.
        reward_file = env_box.root / "reward.txt"
        reward = float(reward_file.read_text().strip()) if reward_file.exists() else -1.0
        try:                                                       # diagnostics only
            info = json.loads(graded.stdout[graded.stdout.index("{"):])
        except Exception:                                          # noqa: BLE001
            info = {"error": (graded.stderr or graded.stdout)[-400:]}
        return {"name": name, "reward": reward, "info": info,
                "seconds": round(time.time() - started, 1),
                "driver_rc": drive.returncode,
                "driver_tail": (drive.stderr or "")[-300:]}
    finally:
        env_box.cleanup()


def verdict(name: str, result: Dict[str, Any], expected: Dict[str, Any]) -> Tuple[bool, str]:
    spec = expected.get(name, {})
    reward = result["reward"]
    problems = []
    if "expect_min" in spec and reward < spec["expect_min"]:
        problems.append(f"reward {reward} < {spec['expect_min']}")
    if "expect_max" in spec and reward > spec["expect_max"]:
        problems.append(f"reward {reward} > {spec['expect_max']}")
    want = spec.get("expect_reason")
    if want and reward == 0.0:
        blob = json.dumps(result["info"])
        if want not in blob:
            problems.append(f"floored for the wrong reason (wanted {want!r})")
    return (not problems), "; ".join(problems)


def summarise(result: Dict[str, Any]) -> str:
    info = result["info"]
    term = info.get("terminal") or {}
    bits = []
    if info.get("terminal_reason"):
        bits.append(str(info["terminal_reason"]))
    if term.get("auc") is not None:
        bits.append(f"auc={term['auc']}")
    if term.get("customers_moved_by_future_rows") is not None:
        bits.append(f"moved={term['customers_moved_by_future_rows']}")
    if term.get("max_abs_delta") is not None:
        bits.append(f"maxd={term['max_abs_delta']}")
    if not info.get("gate_walk_ok", True):
        bits.append(str(info.get("gate_reason")))
    if not info.get("depth_ok", True):
        bits.append(str(info.get("depth_reason")))
    counts = info.get("counts", {})
    if counts:
        bits.append(f"acts={counts.get('accepted_actions')}")
    return "  ".join(bits)[:130]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=4)
    ns = ap.parse_args()

    expected = json.loads((NC / "expected_detail.json").read_text())
    todo = scenarios()
    if ns.only:
        todo = {k: v for k, v in todo.items() if k in set(ns.only)}
    plan = [(f"{k}#{r + 1}" if ns.repeat > 1 else k, k, v)
            for r in range(ns.repeat) for k, v in todo.items()]

    print(f"calibrating {len(plan)} run(s) with {ns.jobs} workers\n")
    print(f"{'scenario':22s} {'reward':>7s}  {'sec':>5s}  detail")
    print("-" * 118)
    rows = []
    with ThreadPoolExecutor(max_workers=ns.jobs) as pool:
        futures = {pool.submit(run_one, key, path): (label, key) for label, key, path in plan}
        for fut in futures:
            pass
        for fut, (label, key) in futures.items():
            result = fut.result()
            ok, why = verdict(key, result, expected)
            rows.append((label, key, result, ok, why))

    rows.sort(key=lambda r: r[0])
    for label, key, result, ok, why in rows:
        print(f"{label:22s} {result['reward']:>7.3f}  {result['seconds']:>5.0f}  {summarise(result)}")

    print("\nchecks vs expected_detail.json")
    all_ok = True
    for label, key, result, ok, why in rows:
        all_ok &= ok
        print(f"  {label:22s} {'PASS' if ok else 'FAIL — ' + why}")

    if ns.repeat > 1:
        print("\ndeterminism")
        by_key: Dict[str, set] = {}
        for label, key, result, ok, why in rows:
            by_key.setdefault(key, set()).add(result["reward"])
        for key, values in sorted(by_key.items()):
            stable = len(values) == 1
            all_ok &= stable
            print(f"  {key:22s} {'stable' if stable else 'FLAKY ' + str(sorted(values))}")

    print(f"\nCALIBRATION {'GREEN' if all_ok else 'RED — fix before shipping'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
