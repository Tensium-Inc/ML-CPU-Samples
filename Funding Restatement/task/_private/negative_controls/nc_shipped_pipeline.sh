#!/usr/bin/env bash
# NEGATIVE -- perfect protocol, the shipped build. Floors on the table.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate || true
op check.release || true
exit 0
