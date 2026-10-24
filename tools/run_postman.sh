#!/usr/bin/env bash
# Run the Postman collection against a throw-away database and server (needs Node.js; Newman is fetched with npx).
#   bash tools/run_postman.sh                 # uses: npx --yes newman
#   NEWMAN=/path/to/newman bash tools/run_postman.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
WORK="$(mktemp -d)"
export DJANGO_SQLITE_PATH="$WORK/postman.sqlite3" DJANGO_DEBUG=True
PYTHON="${PYTHON:-python3}"

"$PYTHON" manage.py migrate -v0
"$PYTHON" manage.py seed_demo >/dev/null
"$PYTHON" manage.py runserver "$PORT" --noreload >"$WORK/server.log" 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true; rm -rf "$WORK"' EXIT
sleep 3

${NEWMAN:-npx --yes newman} run docs/postman/SmartParking.postman_collection.json \
  -e docs/postman/SmartParking.postman_environment.json --env-var "base_url=http://127.0.0.1:$PORT"
