#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
WS_SRC = TASK / "environment" / "workspace"
ENVD = TASK / "environment" / "envd" / "envd.py"
HIDDEN = TASK / "environment" / "hidden"


class DevEnv:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(tempfile.mkdtemp(prefix="devenv-"))
        self.workspace = self.root / "target"
        self.state = self.root / "envstate"
        self.sock = self.root / "envd.sock"
        self.proc: subprocess.Popen | None = None

    def start(self) -> "DevEnv":
        shutil.copytree(WS_SRC, self.workspace)
        self.state.mkdir()
        env = os.environ.copy()
        env.update({
            "ENVD_DEV": "1",
            "WORKSPACE_DIR": str(self.workspace),
            "ENVD_STATE": str(self.state),
            "ENVD_HIDDEN": str(HIDDEN),
            "ENVD_SOCK": str(self.sock),
        })
        self.log = (self.root / "envd.log").open("w")
        self.proc = subprocess.Popen([sys.executable, str(ENVD)], env=env,
                                     stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(200):
            if self.sock.exists():
                return self
            time.sleep(0.05)
        raise RuntimeError(f"envd did not start: {(self.root / 'envd.log').read_text()[-2000:]}")

    def cli(self, *argv: str) -> dict:
        env = os.environ.copy()
        env["ENVD_SOCK"] = str(self.sock)
        proc = subprocess.run([sys.executable, "env_cli.py", *argv], cwd=str(self.workspace),
                              env=env, capture_output=True, text=True)
        try:
            return json.loads(proc.stdout)
        except Exception:                                          # noqa: BLE001
            return {"ok": False, "error": "unparseable", "stdout": proc.stdout[-500:],
                    "stderr": proc.stderr[-500:]}

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self.root, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="leave the temp env in place and print it")
    ap.add_argument("ops", nargs="*", help="ops to drive, e.g. inspect reproduce deploy")
    ns = ap.parse_args()
    env = DevEnv().start()
    try:
        for op in ns.ops:
            t = time.time()
            resp = env.cli(*op.split("="))
            print(f"=== {op}  ({time.time() - t:.1f}s) ===")
            print(json.dumps(resp, indent=2)[:1600])
        if ns.keep:
            print(f"\nworkspace: {env.workspace}\nstate:     {env.state}\nsocket:    {env.sock}")
            return 0
    finally:
        if ns.keep:
            env.stop()
        else:
            env.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
