#!/usr/bin/env bash
# NEGATIVE -- every rule right except that only ONE of the two funded tokens is
# recognised. The status column ships recoded, and two different tokens mean
# funded: QK7 on 51,464 rows and VR9 on 632. VR9 carries exactly as many rows as
# VD4, which means denied, so rarity cannot tell the two apart and both have to
# be put to the oracle. Treating VR9 as anything but funded costs 627 requests,
# 5.6x the 111-request band.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes; write_build "miss_second_funded"
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate || true
op check.release || true
exit 0
