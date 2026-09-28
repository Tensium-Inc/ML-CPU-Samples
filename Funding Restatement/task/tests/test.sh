#!/bin/bash
set -euo pipefail
# The verifier does not always mount tests/ at /tests, so resolve rather than
# assume; a grader that cannot be found reads exactly like a grader that failed.
if [ -f /tests/grade.py ]; then
  exec python3 /tests/grade.py
fi
exec python3 "$(dirname "${BASH_SOURCE[0]}")/grade.py"
