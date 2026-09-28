#!/usr/bin/env python3
"""Client for the gated release service. Sends one JSON request over the unix socket."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys

SOCKET_PATH = os.environ.get("ENVD_SOCK", "/run/envd/envd.sock")

OPS = ["survey", "ledger", "pull_records", "register_audit", "status",
       "rehearse", "deploy.prepare", "deploy.commit", "checkpoint", "incident.read",
       "remediate", "canary.open", "canary.read", "cutover.commit"]


def call(op: str, args: dict) -> dict:
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1800)
        sock.connect(SOCKET_PATH)
    except OSError as exc:
        return {"ok": False, "error": f"release service unreachable at {SOCKET_PATH}: {exc}"}
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
    except Exception as exc:                                           # noqa: BLE001
        return {"ok": False, "error": f"bad response: {exc}",
                "raw": buf[:400].decode("utf-8", "replace")}


def main() -> int:
    ap = argparse.ArgumentParser(description="gated release service")
    ap.add_argument("op", choices=OPS)
    ap.add_argument("--family", default=None, help="remediation family for remediate")
    ap.add_argument("--file", default=None, help="file to read records from")
    ap.add_argument("--patient", default=None, help="patient number for pull_records")
    ap.add_argument("--encounter", default=None, help="encounter id for register_audit")
    ap.add_argument("--limit", default=None, help="row cap for pull_records")
    ns = ap.parse_args()

    args = {k: v for k, v in {"family": ns.family, "file": ns.file, "patient": ns.patient,
                              "encounter": ns.encounter, "limit": ns.limit}.items()
            if v is not None}
    resp = call(ns.op, args)
    print(json.dumps(resp, indent=2, default=str))
    return 0 if resp.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
