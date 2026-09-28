#!/usr/bin/env bash
set -euo pipefail
export FIX_DIR="$(cd "$(dirname "$0")/../serveonly" && pwd)"
source "$(dirname "$0")/_drive_full.sh"
