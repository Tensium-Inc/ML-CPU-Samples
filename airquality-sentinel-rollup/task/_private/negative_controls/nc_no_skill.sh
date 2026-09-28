#!/usr/bin/env bash
# Rank by the raw sensor, no model, no fix. Keeps the discrimination floor measured.
set -euo pipefail
export FIX_DIR="$(cd "$(dirname "$0")/../noskill" && pwd)"
source "$(dirname "$0")/_drive_full.sh"
