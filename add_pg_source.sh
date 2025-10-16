#!/usr/bin/env bash

set -Eeuo pipefail

# Add a PostgreSQL source to the Airweave backend for the
# collection 'helloworld-e4fh2w', targeting your semantic view(s).
#
# Defaults are tuned for your WSL2 setup, but can be overridden via flags.
#
# Usage examples:
#   bash ./add_pg_source.sh
#   bash ./add_pg_source.sh --host 192.168.128.114 --tables project_team_summary_text,employees
#   bash ./add_pg_source.sh --collection helloworld-e4fh2w --database postgres --schema public
#
# Flags:
#   --collection <id>   Default: helloworld-e4fh2w
#   --name <name>       Default: WSL Postgres
#   --host <ip|host>    Default: auto-detected WSL eth0 IP
#   --port <int>        Default: 5432
#   --database <db>     Default: postgres
#   --user <user>       Default: postgres
#   --password <pwd>    Default: smederevo026
#   --schema <schema>   Default: public
#   --tables <csv>      Default: project_team_summary_text,employees
#   --api <url>         Default: http://localhost:8001

COLLECTION="helloworld-e4fh2w"
NAME="WSL Postgres"
HOST=""
PORT=5432
DATABASE="postgres"
DBUSER="postgres"
DBPASSWORD="smederevo026"
SCHEMA="public"
TABLES="project_team_summary_text,employees"
API_BASE="http://localhost:8001"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --collection) COLLECTION="$2"; shift 2;;
    --name) NAME="$2"; shift 2;;
    --host) HOST="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --database) DATABASE="$2"; shift 2;;
    --user) DBUSER="$2"; shift 2;;
    --password) DBPASSWORD="$2"; shift 2;;
    --schema) SCHEMA="$2"; shift 2;;
    --tables) TABLES="$2"; shift 2;;
    --api) API_BASE="$2"; shift 2;;
    -h|--help)
      grep '^#' "$0" | sed -e 's/^# \{0,1\}//'; exit 0;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

detect_wsl_ip() {
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    # Try eth0 first (typical for WSL2)
    ip=$(ip -4 addr show eth0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -n1 || true)
    if [[ -z "$ip" ]]; then
      # Fallback: route trick
      ip=$(ip route get 1 2>/dev/null | awk '{print $7; exit}' || true)
    fi
  fi
  echo "$ip"
}

resolve_host_docker_internal() {
  # Prefer Docker's magic hostname that maps from containers -> host OS
  if getent hosts host.docker.internal >/dev/null 2>&1; then
    echo "host.docker.internal"
    return 0
  fi
  # Fallback: try to resolve via ping (some distros don't have getent)
  if ping -c1 -W1 host.docker.internal >/dev/null 2>&1; then
    echo "host.docker.internal"
    return 0
  fi
  echo ""
}

# For Docker-on-WSL, containers sometimes need the Windows host IP (nameserver in WSL)
detect_windows_host_ip_from_wsl() {
  awk '/nameserver/ {print $2; exit}' /etc/resolv.conf 2>/dev/null || true
}

# For Linux Docker local-postgres setups, containers reach WSL host via docker0 gateway (e.g., 172.17.0.1)
detect_docker_gateway() {
  local gw=""
  if command -v ip >/dev/null 2>&1; then
    gw=$(ip -4 addr show docker0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -n1 || true)
  fi
  # If docker0 exists but we didn't parse it, default to common gateway
  if [[ -z "$gw" ]]; then
    # Probe common default
    gw="172.17.0.1"
  fi
  echo "$gw"
}

if [[ -z "$HOST" ]]; then
  # 1) Best option for Docker Desktop on Windows/WSL
  HOST=$(resolve_host_docker_internal)
  # 2) Fallback to Windows host IP visible from WSL
  if [[ -z "$HOST" ]]; then
    HOST=$(detect_windows_host_ip_from_wsl)
  fi
  # 3) Fallback to docker0 gateway (Linux local Postgres)
  if [[ -z "$HOST" ]]; then
    HOST=$(detect_docker_gateway)
  fi
  if [[ -z "$HOST" ]]; then
    echo "Could not auto-detect a reachable host for containers. Provide --host <ip|host>." >&2
    exit 1
  fi
fi

HEALTH_URL="$API_BASE/health"
SC_URL="$API_BASE/source-connections"

echo "Checking backend health at $HEALTH_URL ..."
if ! curl -sS "$HEALTH_URL" >/dev/null; then
  echo "Backend is not healthy or not reachable at $HEALTH_URL" >&2
  exit 1
fi

echo "Creating PostgreSQL source for collection '$COLLECTION' (host: $HOST) ..."

# Build JSON payload safely
payload=$(cat <<JSON
{
  "short_name": "postgresql",
  "readable_collection_id": "$COLLECTION",
  "name": "$NAME",
  "authentication": {
    "credentials": {
      "host": "$HOST",
      "port": $PORT,
      "database": "$DATABASE",
      "user": "$DBUSER",
      "password": "$DBPASSWORD",
      "schema": "$SCHEMA",
      "tables": "$TABLES"
    }
  },
  "sync_immediately": true
}
JSON
)

# POST request
echo "Posting source-connection payload ..."
http_code=0
resp=$(curl -sS -o /tmp/sc_resp.json -w "%{http_code}" -X POST "$SC_URL" \
  -H 'Content-Type: application/json' \
  --data "$payload")
http_code="$resp"

echo "HTTP $http_code"
echo "Raw response:"
cat /tmp/sc_resp.json || true

# Optional pretty-print if jq is installed
if command -v jq >/dev/null 2>&1; then
  echo "" && echo "Pretty:" && jq . /tmp/sc_resp.json || true
fi

if [[ "$http_code" != "200" && "$http_code" != "201" ]]; then
  echo "\nCreation failed (HTTP $http_code). See message above." >&2
  echo "Tips:"
  echo "- Verify collection exists: curl -sS '$API_BASE/collections' | jq ."
  echo "- Verify source type is available: curl -sS '$API_BASE/sources' | jq ."
  echo "- Check backend logs: docker logs airweave-backend | tail -n 100"
  exit 1
fi

echo "\nDone. To list connections for this collection:"
echo "  curl -sS '$API_BASE/source-connections?collection=$COLLECTION' | jq ."
echo "To watch sync jobs:"
echo "  curl -sS '$API_BASE/sync/jobs' | jq ."
echo "To stream a specific job:"
echo "  curl -N -sS '$API_BASE/sync/job/JOB_ID/subscribe'"
