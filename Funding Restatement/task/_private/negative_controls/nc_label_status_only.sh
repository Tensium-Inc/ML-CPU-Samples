#!/usr/bin/env bash
# NEGATIVE -- every field right except the label, which is read straight off
# form_471_frn_status_name. This is the build the column name invites, and it is
# wrong on 631 requests in two independent ways: 465 carry a real commitment
# with no wave to carry it, and 165 sit in a wave that carried a commitment of
# exactly zero. Each half clears the band alone, so finding one is not enough.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes; write_build "label_status_only"
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate || true
op check.release || true
exit 0
