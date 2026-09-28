#!/usr/bin/env bash
# NEGATIVE -- everything right except the applicant key, left on the name.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes; write_build "name_key"
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate || true
op check.release || true
exit 0
