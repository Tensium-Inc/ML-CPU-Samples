#!/usr/bin/env python3
"""Client for the ops service.

    python3 env_cli.py <op> [--flag value ...]

The service runs elsewhere and keeps its own records. This file only carries your
arguments to it and prints what comes back; editing it changes how you call the
service, not what the service does or what it writes down.

Output is ONE json object and nothing else, so `python3 env_cli.py status |
python3 -c 'import json,sys; ...'` works and a loop that captures stdout cannot
lose an answer. Prose that used to be printed underneath the object now lives
inside it, under `note`.

Start with `status` -- it names the op the service expects next, and prints the
exact command line for it under `next_command`.
"""

from __future__ import annotations

import json
import os
import socket
import sys

SOCK = os.environ.get("OPS_SOCKET", "/run/fundops.sock")


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: env_cli.py <op> [--flag value ...]"}))
        return 2
    try:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.connect(SOCK)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"ops service unreachable at {SOCK}: {exc}"}))
        return 1
    try:
        conn.sendall((json.dumps({"argv": sys.argv[1:]}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        conn.close()

    try:
        response = json.loads(buf.decode() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "error": "malformed response from the ops service"}))
        return 1
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
