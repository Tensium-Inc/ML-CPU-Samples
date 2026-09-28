#!/usr/bin/env bash
# NEGATIVE -- the agent does nothing at all.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
obs status
exit 0
