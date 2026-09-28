#!/usr/bin/env python3
"""Offline calibration battery. No model, no network, free.

Each scenario gets a fresh workspace copy, a fresh state directory and its own
dev daemon on a private socket, then the real tests/grade.py scores it. GREEN
means every positive control hit 1.0 AND every negative floored on the check it
was written to exercise -- a control that floors for the wrong reason has tested
nothing, so the reason is asserted, not just the score.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
WS = TASK / "environment/workspace"
TRUSTED = TASK / "environment/trusted"
DEV_GRADE = HERE / "dev_grade.py"
DEV_DAEMON = HERE / "dev_daemon.py"

SCENARIOS = {
    "gold":                (TASK / "solution/solve.sh",      {"min": 1.0}),
    "alt_correct":         (TASK / "solution/alt_solve.sh",  {"min": 1.0}),
    "alt2_correct":        (TASK / "solution/alt2_solve.sh", {"min": 1.0}),
    # Correct but NOT first try. The control whose absence let a floor ship: it
    # takes a real verdict on a wrong build, fixes it, redeploys and releases.
    "pc_iterating":        (HERE / "positive_controls/pc_iterating.sh",        {"min": 1.0}),
    "nc_shipped":          (HERE / "negative_controls/nc_shipped_pipeline.sh",   {"max": 0.0, "why": "table"}),
    # The control this task turns on: every rule right EXCEPT that the money is
    # read off the adjudicated version. Wrong on 15,133 requests of 55,878, and
    # the local check reports a BETTER number for it than for the correct build.
    # THE CONTROL FOR THIS REVISION'S AXIS. One provenance rule applied to
    # every field: label, key and all three filed_* figures correct,
    # `committed_cents` wrong on 13,585 requests. It scored 1.0 before the
    # deliverable had a field that reads off the other version.
    "nc_one_provenance":  (HERE / "negative_controls/nc_one_provenance.sh",  {"max": 0.0, "why": "table"}),
    "nc_restated_money":   (HERE / "negative_controls/nc_restated_money.sh",     {"max": 0.0, "why": "table"}),
    "nc_cancelled":        (HERE / "negative_controls/nc_cancelled_undecided.sh", {"max": 0.0, "why": "table"}),
    "nc_name_key":         (HERE / "negative_controls/nc_name_key.sh",           {"max": 0.0, "why": "table"}),
    "nc_skip_notes":       (HERE / "negative_controls/nc_skip_notes.sh",         {"max": 0.0, "why": "notes"}),
    "nc_wrong_recovery":   (HERE / "negative_controls/nc_wrong_recovery.sh",     {"max": 0.0, "why": "walk"}),
    "nc_forged_log":       (HERE / "negative_controls/nc_forged_log.sh",         {"max": 0.0, "why": "notes"}),
    "nc_do_nothing":       (HERE / "negative_controls/nc_do_nothing.sh",         {"max": 0.0}),
    "nc_malformed":        (HERE / "negative_controls/nc_malformed_output.sh",   {"max": 0.0, "why": "deliverable"}),
    # The multi-file floor, measured on a trajectory that SOLVES the problem.
    "nc_single_file":      (HERE / "negative_controls/nc_single_file.sh",        {"max": 0.0, "why": "walk"}),
    # THE ONE-SHOT CONTROL: correct build in one pass, no gated walk.
    "nc_one_shot":         (HERE / "negative_controls/nc_one_shot.sh",           {"max": 0.0, "why": "walk"}),
}


def _wait_for_socket(path: Path, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(str(path))
                s.close()
                return True
            except OSError:
                pass
        time.sleep(0.1)
    return False


def run(driver: Path) -> tuple[float, dict]:
    tmp = Path(tempfile.mkdtemp())
    target = tmp / "target"
    shutil.copytree(WS, target)
    state = tmp / "state"
    # Short path: a unix socket path is capped near 100 bytes and the temp roots
    # on macOS are long enough to blow it.
    sock = Path(tempfile.mkdtemp(dir="/tmp")) / "ops.sock"
    reward = tmp / "reward.json"
    reward_txt = tmp / "reward.txt"

    daemon = subprocess.Popen(
        [sys.executable, str(DEV_DAEMON), "--sock", str(sock), "--state", str(state),
         "--trusted", str(TRUSTED), "--workspace", str(target)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for_socket(sock):
            return -1.0, {"error": "dev daemon never came up"}

        env = {
            **os.environ,
            "WORKSPACE_DIR": str(target),
            "OPS_SOCKET": str(sock),
            "OPS_STATE_DIR": str(state),
            "OPS_TRUSTED_DATA": str(TRUSTED),
            "REWARD_PATH": str(reward),
            "REWARD_TXT_PATH": str(reward_txt),
            "PYTHON": sys.executable,
            "PYTHONPATH": str(TASK / "environment/backend"),
        }
        run_proc = subprocess.run(["bash", str(driver)], env=env, cwd=str(target),
                                  capture_output=True, text=True, timeout=3600)
        # A driver that died is not a control that floored. Silently grading its
        # wreckage produces a confident verdict about nothing, which is exactly
        # what happened when a readiness probe was killing the daemon: every
        # scenario reported `notes_unread` and the table looked like a result.
        driver_failed = (
            f"driver exited {run_proc.returncode}: "
            f"{(run_proc.stderr or run_proc.stdout or 'no output').strip()[-200:]}"
            if run_proc.returncode != 0 else ""
        )
        # The shipped grader hardcodes its paths, so calibration goes through
        # the _private wrapper that patches them rather than the image carrying
        # an override the agent could reach.
        proc = subprocess.run(
            [sys.executable, str(DEV_GRADE), "--state", str(state),
             "--trusted", str(TRUSTED), "--workspace", str(target),
             "--reward", str(reward)],
            env=env, cwd=str(target), capture_output=True, text=True, timeout=3600)
    finally:
        daemon.send_signal(signal.SIGTERM)
        daemon.wait(timeout=10)

    m = re.search(r"Final score:\s*([0-9.]+)", proc.stdout)
    score = float(m.group(1)) if m else -1.0
    try:
        detail = json.loads(reward.read_text())["detail"]
        # The acceptance standard reads reward.txt, so calibration asserts it
        # too: present, strictly 0 or 1, and agreeing with the graded score.
        seen = reward_txt.read_text() if reward_txt.exists() else "<absent>"
        expected = "1" if detail.get("strict_pass") else "0"
        if seen != expected:
            detail = {**detail, "reward_txt_mismatch": f"{seen!r} != {expected!r}"}
    except Exception:  # noqa: BLE001
        detail = {"error": (proc.stderr or "no reward file")[-200:]}
    if driver_failed:
        detail["driver_error"] = driver_failed
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(sock.parent, ignore_errors=True)
    return score, detail


def floor_reason(detail: dict) -> str:
    """Which failure is the most informative one, not merely the first.

    `table` is reported ahead of `walk` deliberately. A wrong rebuild cannot
    complete the walk -- `stage.release` needs a clean validate after the
    repair -- so a run with the wrong answer fails BOTH, and saying "the walk
    was incomplete" would hide the reason it was incomplete. Reporting the
    answer first keeps a protocol failure meaning what it says: the walk was
    driven badly, with a rebuild that was already correct.
    """
    if not detail.get("deliverable_ok", True):
        return "deliverable"
    if not detail.get("notes_ok", True):
        return "notes"
    # "nothing_deployed" is a walk failure wearing a table failure's clothes: the
    # table could not be graded BECAUSE the walk never registered a build. The
    # one-shot control lands here, and calling it a table failure would hide the
    # only thing it exists to prove.
    if not detail.get("table_ok", True):
        if str(detail.get("table_reason", "")).startswith("nothing_deployed"):
            return "walk"
        return "table"
    if not detail.get("walk_ok", True) or not detail.get("submitted", True):
        return "walk"
    return "none"


def main() -> int:
    if not (TRUSTED / "erate_frn_status_fy2024.csv.gz").exists():
        print("REFUSING: environment/trusted is empty — run _private/generate_workspace.py")
        return 2

    print(f"{'scenario':20s} {'score':>6s}  {'floored on':12s} detail")
    print("-" * 108)
    ok = True
    for name, (driver, expect) in SCENARIOS.items():
        score, detail = run(driver)
        if detail.get("driver_error") and "min" in expect:
            # Only the positive controls are expected to run clean end to end;
            # several negatives are SUPPOSED to have a driver refused mid-walk.
            print(f"{name:20s} {'':>6s}  {'DRIVER':12s} {detail['driver_error'][:64]}")
            ok = False
            continue
        why = floor_reason(detail)
        note = {
            "deliverable": detail.get("deliverable_reason", ""),
            "notes": detail.get("notes_reason", ""),
            "walk": detail.get("walk_reason", "") or f"submitted={detail.get('submitted')}",
            "table": detail.get("table_reason", ""),
        }.get(why) or detail.get("error", "")
        print(f"{name:20s} {score:>6.3f}  {why:12s} {str(note)[:64]}")
        if "min" in expect and score < expect["min"]:
            print(f"{'':20s}         FAIL: expected >= {expect['min']}")
            ok = False
        if "max" in expect and score > expect["max"]:
            print(f"{'':20s}         FAIL: expected <= {expect['max']}")
            ok = False
        if expect.get("why") and why != expect["why"]:
            print(f"{'':20s}         FAIL: floored on {why!r}, must floor on {expect['why']!r}")
            ok = False

    print(f"\nCALIBRATION {'GREEN' if ok else 'RED -- fix before shipping'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
