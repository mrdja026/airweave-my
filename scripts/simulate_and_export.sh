#!/usr/bin/env bash
set -euo pipefail

# One-click driver: simulate today -> re-sync sources -> export EOD Markdown

# ---- Config (override via env) ---------------------------------------------
API_URL=${API_URL:-http://localhost:8001}
COLLECTION=${COLLECTION:-helloworld-e4fh2w}

PG_HOST=${PG_HOST:-localhost}
PG_PORT=${PG_PORT:-5432}
PG_USER=${PG_USER:-postgres}
PG_DB=${PG_DB:-postgres}

# Optional: provide source IDs explicitly to skip discovery
ACTIONS_SOURCE_ID=${ACTIONS_SOURCE_ID:-}
DELIV_SOURCE_ID=${DELIV_SOURCE_ID:-}

PROJECT=${PROJECT:-BigCompany}
PROMPT_DATE=${PROMPT_DATE:-today}

# ---- Helpers ----------------------------------------------------------------
require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1'" >&2; exit 1; }; }

require_cmd psql
require_cmd curl
require_cmd jq

echo "[1/4] Simulating today (Observe → Plan → Act → Log) ..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -f "$(dirname "$0")/../sql/simulate_day.sql" >/dev/null

discover_source_id() {
  local label=$1; shift
  local name_hint=$1; shift
  local table_hint=$1; shift
  # Try by name first
  local sid
  sid=$(curl -s "$API_URL/source-connections?collection=$COLLECTION" \
    | jq -r --arg NAME "$name_hint" '.[] | select(.name==$NAME) | .id' | head -n1)
  if [[ -n "$sid" && "$sid" != null ]]; then echo "$sid"; return; fi
  # Fallback: match by tables hint if provided
  if [[ -n "$table_hint" ]]; then
    sid=$(curl -s "$API_URL/source-connections?collection=$COLLECTION" \
      | jq -r --arg H "$table_hint" '.[] | select((.authentication.credentials.tables // "") | contains($H)) | .id' | head -n1)
    if [[ -n "$sid" && "$sid" != null ]]; then echo "$sid"; return; fi
  fi
  echo ""  # not found
}

if [[ -z "$ACTIONS_SOURCE_ID" ]]; then
  ACTIONS_SOURCE_ID=$(discover_source_id "actions" "WSL Postgres Actions/Decisions" "performed_actions_text")
fi
if [[ -z "$DELIV_SOURCE_ID" ]]; then
  DELIV_SOURCE_ID=$(discover_source_id "deliverables" "WSL Postgres Constraints/Deliverables" "eod_deliverables_text")
fi

echo "[2/4] Re-syncing sources ..."
if [[ -n "$ACTIONS_SOURCE_ID" ]]; then
  curl -s -X POST "$API_URL/source-connections/$ACTIONS_SOURCE_ID/run" >/dev/null || true
else
  echo "  ⚠ Could not auto-detect Actions/Decisions source; skip. Set ACTIONS_SOURCE_ID to force." >&2
fi
if [[ -n "$DELIV_SOURCE_ID" ]]; then
  curl -s -X POST "$API_URL/source-connections/$DELIV_SOURCE_ID/run" >/dev/null || true
else
  echo "  ⚠ Could not auto-detect Deliverables/Constraints source; skip. Set DELIV_SOURCE_ID to force." >&2
fi

wait_latest_job() {
  local sid=$1
  [[ -z "$sid" ]] && return 0
  local t0=$(date +%s)
  while true; do
    local line
    line=$(curl -s "$API_URL/source-connections/$sid/jobs" \
      | jq -r 'sort_by(.started_at)|reverse|.[0]|.status + "," + (.error // "")') || true
    local status=${line%%,*}
    local err=${line#*,}
    if [[ "$status" == "completed" ]]; then
      return 0
    elif [[ "$status" == "failed" ]]; then
      echo "  ❌ Sync failed for $sid: $err" >&2
      return 1
    fi
    local now=$(date +%s)
    if (( now - t0 > 90 )); then
      echo "  ⏱ Timeout waiting for sync $sid; proceeding." >&2
      return 0
    fi
    sleep 2
  done
}

wait_latest_job "$ACTIONS_SOURCE_ID" || true
wait_latest_job "$DELIV_SOURCE_ID" || true

echo "[3/4] Exporting EOD Markdown ..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$PROJECT" PROMPT_DATE="$PROMPT_DATE" API_URL="$API_URL" COLLECTION="$COLLECTION" \
  bash "$SCRIPT_DIR/eod_export.sh"

echo "[4/4] Done. Check the Demo/ folder for EOD_*.md."

