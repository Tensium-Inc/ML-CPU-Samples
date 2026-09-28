#!/usr/bin/env bash
# NEGATIVE -- a correct build, driven correctly, notes never pulled.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
write_build ""
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate; op check.release
op submit || true
exit 0
