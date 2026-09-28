#!/usr/bin/env bash
# NEGATIVE -- a correct build repaired with families the diagnosis never named.
# Both budgeted repairs are spent guessing, so the walk cannot complete.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes; write_build ""
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_index || true
op diagnostics.read
op recovery.apply --family cache_invalidation || true
op validate || true
exit 0
