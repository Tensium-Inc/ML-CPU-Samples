# Materialise the gold fix into a scratch dir, so every arm is derived from the one copy of it
# that exists (solution/solve.sh) rather than from a second transcription that can drift.
#
#   . _arm.sh          -> $ARM holds codes.py, register.py, serve.py exactly as gold writes them
#   arm_drop <file>    -> revert that module to the shipped one by removing it from the arm
#   arm_python <<'EOF' -> patch the arm in place
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOLVE="$(cd "$HERE/../../solution" && pwd)/solve.sh"
ARM="$(mktemp -d)"
FIX_ONLY=1 bash "$SOLVE" "$ARM"

arm_drop() { rm -f "$ARM/$1"; }
arm_python() { "${PYTHON:-python3}" - "$ARM"; }
