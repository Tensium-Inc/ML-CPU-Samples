#!/usr/bin/env bash
# NEGATIVE -- the control this task turns on. Every rule right EXCEPT that the
# money is read off the adjudicated version. Wrong on 15,133 requests of 55,878,
# and the local check reports a BETTER number for it than for the correct build.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes; write_build "restated_money"
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate || true
op check.release || true
exit 0
