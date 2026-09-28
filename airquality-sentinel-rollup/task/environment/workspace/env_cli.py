#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import socket
import sys

SOCKET_PATH = os.environ.get("ENVD_SOCK", "/run/envd/envd.sock")

OPS = ["inspect", "profile", "sample_records", "feature_audit", "status",
       "reproduce", "deploy", "validate", "diagnostics.read", "recovery.apply",
       "promote", "submit"]


def call(op: str, args: dict) -> dict:
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1800)
        sock.connect(SOCKET_PATH)
    except OSError as exc:
        return {"ok": False, "error": f"ops service unreachable at {SOCKET_PATH}: {exc}"}
    with sock:
        sock.sendall(json.dumps({"op": op, "args": args}).encode() + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    try:
        return json.loads(buf.decode())
    except Exception as exc:                                      # noqa: BLE001
        return {"ok": False, "error": f"bad response: {exc}", "raw": buf[:400].decode("utf-8", "replace")}


def main() -> int:
    ap = argparse.ArgumentParser(description="gated ops service")
    ap.add_argument("op", choices=OPS)
    ap.add_argument("--family", default=None, help="recovery family for recovery.apply")
    ap.add_argument("--file", default=None, help="file to sample from")
    ap.add_argument("--at", default=None, help="hour to centre on, e.g. 2005-01-20T14:00:00")
    ns = ap.parse_args()

    args = {k: v for k, v in
            {"family": ns.family, "file": ns.file, "at": ns.at}.items() if v is not None}
    resp = call(ns.op, args)
    print(json.dumps(resp, indent=2, default=str))
    return 0 if resp.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
