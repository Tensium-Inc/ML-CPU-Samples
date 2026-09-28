#!/usr/bin/env python3
"""Thin client for the root-owned Capital Bike release service."""
from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path


SOCKET_PATH = Path("/run/capital-bike-task/ops.sock")


def call_socket(argv: list[str]) -> int:
    request = (json.dumps({"argv": argv}, separators=(",", ":")) + "\n").encode("ascii")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(SOCKET_PATH))
        client.sendall(request)
        chunks = []
        while True:
            block = client.recv(65536)
            if not block:
                break
            chunks.append(block)
            if b"\n" in block:
                break
    reply = json.loads(b"".join(chunks).splitlines()[0].decode("ascii"))
    print(json.dumps(reply.get("payload", {}), indent=2, sort_keys=True))
    return int(reply.get("returncode", 1))


def main() -> int:
    argv = sys.argv[1:]
    if argv == ["help"]:
        print("investigation: inspect.contract inspect.exports profile.current probe.schema probe.leakage probe.year_bridge probe.commute probe.horizon hypothesis.commit")
        print("release: test.visible backtest.replay candidate.attest reproduce stage.open deploy.prepare deploy.commit validate diagnostics.read recovery.plan recovery.apply recovery.verify cache.audit candidate.revise audit.horizon audit.intervals promote.canary validate.canary promote.production freeze submit")
        return 0
    deadline = time.time() + 5.0
    while time.time() < deadline and not SOCKET_PATH.is_socket():
        time.sleep(0.05)
    if not SOCKET_PATH.is_socket():
        print(json.dumps({"accepted": False, "error": "ops_socket_unavailable"}, indent=2))
        return 70
    try:
        return call_socket(argv)
    except (OSError, ValueError) as exc:
        print(json.dumps({"accepted": False, "error": f"service_unavailable:{exc}"}, indent=2))
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
