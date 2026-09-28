#!/usr/bin/env python3
"""Thin shim. The probe implementation is baked root-only into the image, never shipped here."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else False
IMPL = (Path("/opt/task/probe/terminal_probe.py") if _ROOT
        else Path(os.environ.get("PROBE_IMPL", "/opt/task/probe/terminal_probe.py")))


def main() -> int:
    if not IMPL.exists():
        print(json.dumps({"healthy": False,
                          "reason": f"probe_implementation_missing:{IMPL}"}))
        return 0
    proc = subprocess.run([sys.executable, str(IMPL)], capture_output=True, text=True)
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    if not lines:
        print(json.dumps({"healthy": False,
                          "reason": f"probe_no_output:{proc.stderr.strip()[-200:]}"}))
        return 0
    print(lines[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
