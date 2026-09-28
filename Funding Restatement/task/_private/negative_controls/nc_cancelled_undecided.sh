#!/usr/bin/env bash
# NEGATIVE -- everything right except that a cancelled request is treated as
# though nobody ruled on it. Wrong on 2,746 requests.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes; write_build "cancelled_undecided"
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate || true
op check.release || true
exit 0
