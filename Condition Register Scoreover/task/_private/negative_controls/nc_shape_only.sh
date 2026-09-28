#!/usr/bin/env bash
# The export is collapsed to one row per encounter, the fault the checkpoint actually names,
# and nothing else is touched. Passes every gate and dies at the terminal on the value.
set -euo pipefail
. "$(dirname "$0")/_arm.sh"
arm_drop register.py
arm_drop codes.py
export FIX_DIR="$ARM"
source "$(dirname "$0")/_drive_full.sh"
