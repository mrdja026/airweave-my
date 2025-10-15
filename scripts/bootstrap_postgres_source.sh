#!/usr/bin/env bash
set -euo pipefail

# Minimal bootstrap for creating a collection, adding a PostgreSQL source (no schedule),
# triggering a sync, listing jobs (no jq), and running a smoke-test search.

# Configurable via env vars or flags
API_URL=${API_URL:-http://localhost:8001}
COLLECTION_NAME=${COLLECTION_NAME:-app-data}
SOURCE_NAME=${SOURCE_NAME:-postgres-app}

# DB connection for your corp Postgres (used by the PostgreSQL source)
DB_HOST=${DB_HOST:-host.docker.internal}  # If this fails, use your WSL eth0 IP
DB_PORT=${DB_PORT:-5432}
DB_NAME=${DB_NAME:-postgres}
DB_USER=${DB_USER:-postgres}
DB_PASSWORD=${DB_PASSWORD:-smederevo026}
DB_SCHEMA=${DB_SCHEMA:-public}
DB_TABLES=${DB_TABLES:-*}

usage() {
  cat <<EOF
Usage: API_URL=... COLLECTION_NAME=... DB_*=... $(basename "$0")

Environment variables:
  API_URL         Default: http://localhost:8001
  COLLECTION_NAME Default: app-data
  SOURCE_NAME     Default: postgres-app

  DB_HOST         Default: host.docker.internal (use WSL eth0 IP if needed)
  DB_PORT         Default: 5432
  DB_NAME         Default: postgres
  DB_USER         Default: postgres
  DB_PASSWORD     Default: smederevo026
  DB_SCHEMA       Default: public
  DB_TABLES       Default: *

Steps performed:
  1) Find or create collection; capture readable_id
  2) Create PostgreSQL source (no schedule, no immediate run)
  3) Trigger collection refresh (fallback runs without Temporal)
  4) List jobs for the source (no jq)
  5) Smoke test search (query: "hello")
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

require_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for basic JSON parsing" >&2
    exit 1
  fi
}

echo "[1/5] Finding or creating collection '${COLLECTION_NAME}'..."
require_python

# Try to find an existing collection by name
EXISTING=$(curl -sS "${API_URL}/collections/?limit=1000" || true)

READABLE_ID=$(printf '%s' "$EXISTING" | python3 - "$COLLECTION_NAME" <<'PY'
import sys, json, os
name = os.environ.get('COLLECTION_NAME') or (sys.argv[1] if len(sys.argv) > 1 else None)
try:
    data = json.load(sys.stdin)
except Exception:
    data = []
rid = None
for c in data:
    if isinstance(c, dict) and c.get('name') == name:
        rid = c.get('readable_id')
        break
if rid:
    print(rid)
PY
)

if [[ -z "${READABLE_ID}" ]]; then
  echo "No existing collection found. Creating a new one..."
  CREATE_OUT=$(curl -sS -X POST "${API_URL}/collections/" \
    -H 'Content-Type: application/json' \
    -d "{\"name\": \"${COLLECTION_NAME}\"}")
  echo "Create response: ${CREATE_OUT}"
READABLE_ID=$(printf '%s' "$CREATE_OUT" | python3 - <<'PY'
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('readable_id',''))
except Exception:
    print('')
PY
)
if [[ -z "${READABLE_ID}" ]]; then
  # Fallback to sed if JSON parsing fails
  READABLE_ID=$(printf '%s' "$CREATE_OUT" | sed -n 's/.*"readable_id":"\([^"]*\)".*/\1/p')
fi
fi

if [[ -z "${READABLE_ID}" ]]; then
  echo "Failed to obtain collection readable_id." >&2
  exit 1
fi
echo "Using collection readable_id: ${READABLE_ID}"

echo "[2/5] Creating PostgreSQL source '${SOURCE_NAME}' (no schedule, no immediate run)..."
SRC_OUT=$(curl -sS -X POST "${API_URL}/source-connections" \
  -H 'Content-Type: application/json' \
  -d "{
    \"name\": \"${SOURCE_NAME}\",
    \"short_name\": \"postgresql\",
    \"readable_collection_id\": \"${READABLE_ID}\",
    \"sync_immediately\": false,
    \"schedule\": { \"cron\": null },
    \"authentication\": {
      \"credentials\": {
        \"host\": \"${DB_HOST}\",
        \"port\": ${DB_PORT},
        \"database\": \"${DB_NAME}\",
        \"user\": \"${DB_USER}\",
        \"password\": \"${DB_PASSWORD}\",
        \"schema\": \"${DB_SCHEMA}\",
        \"tables\": \"${DB_TABLES}\"
      }
    }
  }") || true

echo "Create source response: ${SRC_OUT}"

# Extract source_connection id from response; if not present, try to find by name
SC_ID=$(printf '%s' "$SRC_OUT" | python3 - <<'PY'
import sys, json
try:
    data = json.load(sys.stdin)
    print((data or {}).get('id',''))
except Exception:
    print('')
PY
)

if [[ -z "${SC_ID}" ]]; then
  echo "Falling back to locating source by name..."
  LIST_OUT=$(curl -sS "${API_URL}/source-connections?limit=1000" || true)
  export SOURCE_NAME READABLE_ID
  SC_ID=$(printf '%s' "$LIST_OUT" | python3 - <<'PY'
import sys, json, os
name = os.environ['SOURCE_NAME']
rid = os.environ['READABLE_ID']
try:
    data = json.load(sys.stdin)
except Exception:
    data = []
out = ''
for item in data:
    if isinstance(item, dict) and item.get('name') == name and item.get('readable_collection_id') == rid:
        out = item.get('id','')
        break
print(out)
PY
)
fi

if [[ -z "${SC_ID}" ]]; then
  echo "Failed to determine source_connection id. Please check the previous responses." >&2
  exit 1
fi
echo "Using source_connection id: ${SC_ID}"

# Find the system Connection id for the source (not SourceConnection id)
echo "[3/6] Locating system connection for the source..."
CONNS=$(curl -sS "${API_URL}/connections/list" || true)
export SOURCE_NAME
CONN_ID=$(printf '%s' "$CONNS" | python3 - <<'PY'
import sys, json, os
name = os.environ['SOURCE_NAME']
try:
    data = json.load(sys.stdin)
except Exception:
    data = []
# Heuristic: match by name and integration_type == 'SOURCE'
out = ''
for c in data:
    if isinstance(c, dict) and c.get('name') == name and c.get('integration_type') == 'SOURCE':
        out = c.get('id','')
        break
print(out)
PY
)
if [[ -z "${CONN_ID}" ]]; then
  echo "Failed to locate system connection id for source '${SOURCE_NAME}'." >&2
  echo "Raw connections payload:" >&2
  echo "$CONNS" >&2
  exit 1
fi
echo "Using connection id: ${CONN_ID}"

# Create a Sync via API (no cron), run immediately; use native Qdrant destination (reserved UUID)
echo "[4/6] Creating and running a Sync (no schedule)..."
SYNC_OUT=$(curl -sS -X POST "${API_URL}/sync/" \
  -H 'Content-Type: application/json' \
  -d "{
    \"name\": \"Sync for ${SOURCE_NAME}\",
    \"source_connection_id\": \"${CONN_ID}\",
    \"destination_connection_ids\": [\"11111111-1111-1111-1111-111111111111\"],
    \"run_immediately\": true
  }") || true
echo "create sync response: ${SYNC_OUT}"

echo "[5/6] Listing jobs for source ${SC_ID} (raw JSON, no jq):"
curl -sS "${API_URL}/source-connections/${SC_ID}/jobs" || true
echo

echo "[6/6] Smoke test search (query=hello):"
curl -sS -X POST "${API_URL}/collections/${READABLE_ID}/search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"hello"}' || true
echo

echo "Done. If DB host resolution fails, set DB_HOST to your WSL eth0 IP and rerun."
