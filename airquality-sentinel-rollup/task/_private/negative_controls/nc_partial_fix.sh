#!/usr/bin/env bash
# Half the fix: the rolling mean is right, the serving path still withholds the
# overnight hours. Must score 0.0 -- proves the second file is load-bearing.
set -euo pipefail
export FIX_DIR="$(cd "$(dirname "$0")/../partial" && pwd)"
source "$(dirname "$0")/_drive_full.sh"
