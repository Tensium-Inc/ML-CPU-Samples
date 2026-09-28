#!/usr/bin/env python3
"""Run the real grader against a calibration sandbox. _private only; never shipped.

`tests/grade.py` hardcodes where the service's record, the trusted data and the
reward live, and it should: a grader that lets any of those be redirected can be
pointed at state the agent controls, and leaving the lever in the image is the
weakness whatever the intent.

Offline calibration still needs to point somewhere else, so it patches the
module here instead of the image carrying an override. Same grader, same checks,
same code path -- only the constants differ, and only in a file the agent never
sees.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--trusted", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--reward", required=True)
    parser.add_argument("--backend", default=str(TASK / "environment/backend"))
    args = parser.parse_args()

    # The grader imports the backend from /opt/task in the image.
    sys.path.insert(0, args.backend)

    spec = importlib.util.spec_from_file_location("grade", TASK / "tests/grade.py")
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)

    grade.STATE_DIR = Path(args.state)
    grade.TRUSTED = Path(args.trusted)
    grade.WORKSPACE = Path(args.workspace)
    grade.REWARD_PATH = Path(args.reward)
    # REWARD_TXT reads its own environment override, which calibration sets;
    # the diagnostics file has none, on purpose -- it is not a reward location
    # and the image must not carry a lever for it. So it is patched here, like
    # every other hardcoded path.
    grade.GRADE_INFO = Path(args.reward).with_name("grade_info.json")
    grade.DELIVERABLE = Path(args.workspace) / "harness.py"

    grade.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
