#!/usr/bin/env python3
"""Offline stand-in for the shipped daemon. Never shipped; _private only.

The real daemon hardcodes its socket, state directory and trusted data, on
purpose: nothing outside the image should be able to redirect any of them. That
makes it unusable on a laptop, so calibration gets this instead — the same
Broker, the same gates, the same log, with the paths passed in.

What it does NOT relax is the thing under test. The broker is still the only
route to the state, the drivers still reach it over a socket, and nothing a
driver writes into its workspace copy is visible to it. A control that forges an
action log still forges it somewhere nothing reads.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "environment/backend"))

import broker as broker_module  # noqa: E402
from broker import Broker  # noqa: E402

_LOCK = threading.Lock()


def serve(sock_path: str, state_dir: str, trusted: str, workspace: str) -> None:
    # The broker hardcodes the agent workspace, as it should -- taking it from
    # the environment would leave a lever in the image pointing at what gets
    # deployed. Calibration redirects it by patching the module, which is only
    # possible from here, and this file never ships.
    broker_module.WORKSPACE = Path(workspace)
    broker = Broker(state_dir, trusted)

    if os.path.exists(sock_path):
        os.remove(sock_path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(16)
    sys.stderr.write(f"dev daemon on {sock_path}\n")
    sys.stderr.flush()

    while True:
        try:
            conn, _ = srv.accept()
        except OSError:  # noqa: PERF203
            continue
        # Mirrors the shipped daemon: a caller that disconnects mid-call must
        # not end the accept loop. This is where the readiness probe used to
        # kill the service, which made every driver fail silently on its first
        # op and every control report a verdict about nothing.
        try:
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            if not buf.strip():
                continue
            with _LOCK:
                resp = broker.handle(json.loads(buf.decode()).get("argv", []))
        except Exception as exc:  # noqa: BLE001
            resp = {"ok": False, "error": f"service error: {exc}"}
        try:
            conn.sendall((json.dumps(resp) + "\n").encode())
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sock", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--trusted", required=True)
    p.add_argument("--workspace", required=True)
    a = p.parse_args()
    serve(a.sock, a.state, a.trusted, a.workspace)
