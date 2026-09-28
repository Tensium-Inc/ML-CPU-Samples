#!/usr/bin/env bash
# POSITIVE CONTROL -- correct, but NOT first try. Must score exactly 1.0.
#
# This is the control whose absence let a floor ship. Every other control in this
# battery either has the right answer immediately or the wrong answer
# permanently; none of them ITERATES, which is what every real run does. Four
# runs out of four were floored by a validate budget that a first-try trajectory
# never noticed, three of them holding a perfect table.
#
# The shape: deploy a wrong build, take a real verdict on it, fix it, redeploy,
# recover again, take a second real verdict, and release. If the ration cannot
# afford that, it is not a ration -- it is a floor.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../negative_controls/_common.sh"

read_all_notes

# --- attempt 1: money read off the wrong version -------------------------
write_build "restated_money"
op reproduce
op deploy
op validate                       # dirty: the injected fault, and it must be FREE
op diagnostics.read
op recovery.apply --family stale_applicant_cache
op validate                       # dirty: a real verdict on a wrong build

# --- attempt 2: money fixed, the cancelled question still wrong ----------
write_build "cancelled_undecided"
op deploy
op validate                       # dirty: a second real verdict

# --- attempt 3: correct ---------------------------------------------------
write_build ""
op deploy
op validate                       # clean
op check.release
op submit
