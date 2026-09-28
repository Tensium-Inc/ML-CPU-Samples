#!/usr/bin/env python3
"""Root-owned ops daemon. Started before the agent shell; the agent never runs it.

The agent is an unprivileged uid with no route to the authoritative state, the
action log, the trusted transaction copy, or the reference rebuild. Its only
contact with any of that is a line of JSON over a unix socket, and the broker
decides what comes back.

There is no sudo or setuid hop anywhere in this path, deliberately: a served
sandbox sets `no_new_privs`, which blocks escalation regardless of what the
image says, and a service that needed to escalate would wedge on the agent's
first gated op and floor the whole run on infrastructure rather than on the task.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from broker import Broker

# Hardcoded, not read from the environment: nothing outside this image should be
# able to redirect the state, the trusted data, or the socket.
SOCK = "/run/fundops.sock"
STATE_DIR = "/var/lib/fundops"
TRUSTED_DATA = "/opt/task/data"
CLIENT_GROUP = "ubuntu"

_LOCK = threading.Lock()


def serve() -> None:
    if os.path.exists(SOCK):
        os.remove(SOCK)
    os.makedirs(STATE_DIR, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)          # root only; the agent cannot read or write it
    broker = Broker(STATE_DIR, TRUSTED_DATA)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o660)
    try:
        import grp

        os.chown(SOCK, 0, grp.getgrnam(CLIENT_GROUP).gr_gid)   # root:ubuntu, 0660
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"warn: could not chown socket to {CLIENT_GROUP}: {exc}\n")
    srv.listen(32)
    sys.stderr.write(f"funding ops daemon listening on {SOCK}\n")
    sys.stderr.flush()

    while True:
        try:
            conn, _ = srv.accept()
        except OSError as exc:  # noqa: PERF203
            sys.stderr.write(f"accept failed: {exc}\n")
            continue
        # One client must never be able to take the service down. A caller that
        # disconnects mid-call -- an interrupted env_cli.py, or a readiness
        # probe that opens and closes -- makes the reply raise BrokenPipeError,
        # and an unguarded write here ends the accept loop and the episode with
        # it. The whole exchange is wrapped, and the connection is closed
        # whatever happens.
        try:
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            if not data.strip():
                continue
            request = json.loads(data.decode())
            with _LOCK:                 # one state transition at a time
                response = broker.handle(request.get("argv", []))
        except Exception as exc:  # noqa: BLE001
            response = {"ok": False, "error": f"service error: {exc}"}
        try:
            conn.sendall((json.dumps(response) + "\n").encode())
        except OSError:
            pass                        # caller went away; its loss, not ours
        finally:
            try:
                conn.close()
            except OSError:
                pass


if __name__ == "__main__":
    serve()
