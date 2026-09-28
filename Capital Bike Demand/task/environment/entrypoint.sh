#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="/var/lib/capital-bike-task"
SOCKET_DIR="/run/capital-bike-task"
SOCKET_PATH="/run/capital-bike-task/ops.sock"
LOG_PATH="$STATE_DIR/service.log"

if [ "$(id -u)" -ne 0 ]; then
  echo "task entrypoint must start as root" >&2
  exit 77
fi

mkdir -p "$STATE_DIR" "$SOCKET_DIR"
find "$STATE_DIR" -mindepth 1 -depth -delete
if [ -S "$SOCKET_PATH" ]; then
  unlink "$SOCKET_PATH"
fi
chmod 700 "$STATE_DIR"
chmod 755 "$SOCKET_DIR"

python3 /opt/task/backend/service.py --initialize
python3 /opt/task/backend/service.py --serve >"$LOG_PATH" 2>&1 &

for _ in $(seq 1 100); do
  if [ -S "$SOCKET_PATH" ]; then
    break
  fi
  sleep 0.05
done
if [ ! -S "$SOCKET_PATH" ]; then
  tail -n 30 "$LOG_PATH" >&2 || true
  echo "release service did not start" >&2
  exit 70
fi

exec "$@"
