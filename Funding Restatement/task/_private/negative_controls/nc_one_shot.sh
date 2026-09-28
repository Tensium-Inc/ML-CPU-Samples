#!/usr/bin/env bash
# NEGATIVE -- THE ONE-SHOT CONTROL. A perfectly correct build written in one pass
# and submitted without the gated walk. Exact table, and the score must be zero.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes; write_build ""
python3 "$WS/harness.py" --data-root "$WS/data" --out "$WS/request_table.csv"
obs status
exit 0
