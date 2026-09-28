#!/usr/bin/env bash
# Correct logic, but the archive is vendored INTO the release so the artifact stops depending on
# anything outside itself. The release must carry code, not data. Must score 0.
set -euo pipefail
. "$(dirname "$0")/_arm.sh"
export FIX_DIR="$ARM"
export AFTER_FIX_HOOK='cp data/encounters.csv src/archive_snapshot.csv'
source "$(dirname "$0")/_drive_full.sh"
