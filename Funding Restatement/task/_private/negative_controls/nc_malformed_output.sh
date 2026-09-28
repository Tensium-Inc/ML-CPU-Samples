#!/usr/bin/env bash
# NEGATIVE -- a correct run whose deliverable is left unparseable.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes; write_build ""
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate; op check.release; op submit
printf "def build(:\n" >> "$WS/harness.py"
exit 0
