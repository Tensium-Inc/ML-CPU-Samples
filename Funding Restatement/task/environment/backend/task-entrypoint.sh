#!/bin/sh
# Root ENTRYPOINT: stand the ops daemon up before the agent has a shell.
#
# PID 1 IS the daemon. That is what keeps the container alive and serving, and
# it is the shape the platform expects: it starts the container, then runs the
# agent's commands as `ubuntu` itself. The entrypoint does not demote anything
# and does not exec a shell -- the earlier versions did both, and each one
# either ended the container the moment nothing was attached to it or left the
# service running under a process the platform had no reason to keep.
#
# There is no sudo/setuid hop anywhere: a served sandbox sets no_new_privs. The
# daemon runs as root and demotes candidate code with setpriv, which is a
# privilege DROP and therefore still permitted.
set -e

# Authoritative state and action log: root-only, unreachable by the agent's uid.
mkdir -p /var/lib/fundops
chown root:root /var/lib/fundops
chmod 700 /var/lib/fundops

mkdir -p /run

exec python3 /opt/task/daemon.py
