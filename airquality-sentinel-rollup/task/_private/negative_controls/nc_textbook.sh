#!/usr/bin/env bash
# THE control: the serving path repaired so every hour comes back, and the
# rolling mean still averaging the logger's not-recorded marker as though it were a reading.
# Passes the smoke tests, passes validate, drives the full walk, and is wrong.
set -euo pipefail
export FIX_DIR="$(cd "$(dirname "$0")/../textbook" && pwd)"
source "$(dirname "$0")/_drive_full.sh"
