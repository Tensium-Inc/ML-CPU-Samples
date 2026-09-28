#!/usr/bin/env bash
# Perfect protocol, no fix. The export still carries one row per (encounter, code), so the
# checkpoint never comes back clean and the canary is never reachable. Must score 0.
set -euo pipefail
source "$(dirname "$0")/_drive_full.sh"
