#!/usr/bin/env bash
set -uo pipefail
TASK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SLUG="$(basename "$TASK_DIR")"
WORK="$(mktemp -d)"
NAME="retail-asof-ship-$$"
trap 'docker rm -f "$NAME" >/dev/null 2>&1; rm -rf "$WORK"' EXIT

echo "== package"
ZIP=$(bash "$TASK_DIR/_private/package.sh" | awk '/^zip:/ {print $2}')
[ -f "$ZIP" ] || { echo "FAIL: no zip produced"; exit 1; }
echo "   $ZIP"

echo "== extract to a clean dir"
unzip -q "$ZIP" -d "$WORK"
EXTRACT="$WORK/$SLUG"
[ -d "$EXTRACT/_private" ] && { echo "FAIL: _private shipped"; exit 1; }
echo "   $(find "$EXTRACT" -type f | wc -l) files, no _private"

echo "== build from the extraction"
docker build -q -t airquality:ship "$EXTRACT/environment" >/dev/null || { echo "FAIL: build"; exit 1; }

echo "== boot + gold walk + grade"
docker run -d --name "$NAME" airquality:ship sleep infinity >/dev/null
for _ in $(seq 1 100); do docker exec "$NAME" test -S /run/envd/envd.sock 2>/dev/null && break; sleep 0.2; done
docker cp "$EXTRACT/tests" "$NAME:/tests" >/dev/null
docker cp "$EXTRACT/solution" "$NAME:/solution" >/dev/null
docker exec -u root "$NAME" chmod -R go-rwx /tests
docker exec -u ubuntu -w /workspace/target "$NAME" bash /solution/solve.sh | tail -1
docker exec -u root "$NAME" bash /tests/test.sh | head -1
REWARD=$(docker exec -u root "$NAME" cat /logs/verifier/reward.txt | tr -d '[:space:]')

echo "== result"
if [ "$REWARD" = "1" ]; then echo "SHIP CHECK: GREEN (reward.txt = $REWARD from a clean extraction)"; exit 0
else echo "SHIP CHECK: RED (reward.txt = '${REWARD:-<missing>}')"; exit 1; fi
