#!/usr/bin/env bash
# NEGATIVE -- the plausible partial answer, and the control for the axis this
# revision adds.
#
# It works out the thing the task is actually about -- that a request exists in
# two versions and the as-filed one is the observation -- and then applies that
# single rule to every field, including the one field that is read off the other
# version. Label, applicant key and all three filed_* figures are correct.
# `committed_cents` is wrong on 13,585 requests.
#
# Before this revision the deliverable had no field that punished it, so a build
# with one provenance rule scored 1.0. That is why the last evaluation went 4/4.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
read_all_notes; write_build "one_provenance"
op reproduce; op deploy; op validate; op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate || true
op check.release || true
exit 0
