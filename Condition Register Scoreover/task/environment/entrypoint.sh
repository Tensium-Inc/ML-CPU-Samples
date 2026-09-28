#!/bin/bash

set -euo pipefail

AGENT_UID=1000
AGENT_GID=1000

if [ "$(id -u)" = "0" ]; then

  if [ -e /tests ]; then
    chown -R root:root /tests 2>/dev/null || true
    chmod -R go-rwx  /tests 2>/dev/null || true
  fi

  if [ ! -S /run/envd/envd.sock ]; then
    mkdir -p /run/envd /var/log
    python3 /opt/envd/envd.py >>/var/log/envd.log 2>&1 &
    for _ in $(seq 1 150); do
      [ -S /run/envd/envd.sock ] && break
      sleep 0.1
    done
    if [ ! -S /run/envd/envd.sock ]; then
      echo "FATAL: the release service failed to start; see /var/log/envd.log" >&2
      tail -20 /var/log/envd.log >&2 || true
      exit 1
    fi
  fi

  exec setpriv --reuid="$AGENT_UID" --regid="$AGENT_GID" --init-groups "$@"
fi

exec "$@"
