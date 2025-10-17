#!/usr/bin/env bash
set -euo pipefail

# Add a sick-leave (Availability) event into your host Postgres,
# then trigger Airweave source re-syncs, and print a ready UI prompt.
#
# Env overrides (all optional):
#   PG_HOST=localhost PG_PORT=5432 PG_USER=postgres PG_DB=postgres
#   PROJECT=BigCompany PLAN_DATE=2025-10-16 DUE_DATE=2025-10-20
#   CLIENT_NAME="Client A" PRIORITY=Medium REQUESTED_BY=HR STATUS=Open
#   DESCRIPTION="Alice called in sick today; reassign critical tasks to maintain deadlines"
#   API_URL=http://localhost:8001 COLLECTION=helloworld-e4fh2w
#   EVENTS_SOURCE_ID=<uuid> DELIV_SOURCE_ID=<uuid>   # optional explicit IDs
#
# Requires: psql, curl, jq. If your DB requires a password, set PGPASSWORD.

PG_HOST=${PG_HOST:-localhost}
PG_PORT=${PG_PORT:-5432}
PG_USER=${PG_USER:-postgres}
PG_DB=${PG_DB:-postgres}

PROJECT=${PROJECT:-BigCompany}
PLAN_DATE=${PLAN_DATE:-2025-10-16}
DUE_DATE=${DUE_DATE:-2025-10-20}

CLIENT_NAME=${CLIENT_NAME:-Client A}
PRIORITY=${PRIORITY:-Medium}
REQUESTED_BY=${REQUESTED_BY:-HR}
STATUS=${STATUS:-Open}
DESCRIPTION=${DESCRIPTION:-Alice called in sick today; reassign critical tasks to maintain deadlines}

API_URL=${API_URL:-http://localhost:8001}
COLLECTION=${COLLECTION:-helloworld-e4fh2w}

require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1'" >&2; exit 1; }; }
require psql; require curl; require jq

sql_escape() { sed "s/'/''/g" <<< "$1"; }

echo "[0/4] Sanity checks (schema presence) ..."
HAS_PROJECTS=$(psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -tAc "SELECT to_regclass('public.projects') IS NOT NULL") || true
if [[ "$HAS_PROJECTS" != "t" ]]; then
  echo "  ! Table public.projects is missing in database '$PG_DB'."
  if [[ "${AUTO_BOOTSTRAP:-false}" == "true" ]]; then
    echo "  -> AUTO_BOOTSTRAP=true: creating minimal public.projects ..."
    psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -c "CREATE TABLE IF NOT EXISTS public.projects (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL);" >/dev/null
    echo "     done."
  else
    echo "  -> Run one of the following, then re-run this script:"
    echo "     - make -C airweave seed-db HOST_PG_PORT=$PG_PORT PG_USER=$PG_USER PG_DB=$PG_DB"
    echo "     - or: psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DB -f airweave/sql/seed_semantic_demo.sql"
    echo "       then: psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DB -f airweave/sql/seed_project_events.sql"
    exit 2
  fi
fi

HAS_EVENTS=$(psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -tAc "SELECT to_regclass('public.project_events') IS NOT NULL") || true
if [[ "$HAS_EVENTS" != "t" ]]; then
  echo "  ! Table public.project_events is missing; creating minimal table (demo-only)."
  psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -c "\
    CREATE TABLE IF NOT EXISTS public.project_events (\
      id SERIAL PRIMARY KEY,\
      project_id INT NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,\
      client_name TEXT NOT NULL, event_type TEXT NOT NULL, priority TEXT NOT NULL,\
      requested_at TIMESTAMPTZ NOT NULL DEFAULT now(), requested_by TEXT, description TEXT,\
      deadline DATE, estimate_hours INT, status TEXT NOT NULL DEFAULT 'Open', outcome TEXT\
    );" >/dev/null
fi

echo "[1/4] Inserting Availability (sick leave) for project '$PROJECT' on $PLAN_DATE ..."
TS="${PLAN_DATE} 09:00:00+00"  # fixed morning timestamp in UTC for deterministic matching
PROJ_ESC=$(sql_escape "$PROJECT")
CLIENT_ESC=$(sql_escape "$CLIENT_NAME")
PRIO_ESC=$(sql_escape "$PRIORITY")
BY_ESC=$(sql_escape "$REQUESTED_BY")
DESC_ESC=$(sql_escape "$DESCRIPTION")
STATUS_ESC=$(sql_escape "$STATUS")

SQL=$(cat <<SQL
WITH pid AS (SELECT id FROM public.projects WHERE name='${PROJ_ESC}')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, status)
SELECT id, '${CLIENT_ESC}', 'Availability', '${PRIO_ESC}', TIMESTAMPTZ '${TS}', '${BY_ESC}', '${DESC_ESC}', '${STATUS_ESC}'
FROM pid;
SQL
)

psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -c "$SQL" >/dev/null

echo "[2/4] Verifying insert ..."
VERIFY_SQL=$(cat <<SQL
SELECT COUNT(*) AS availability_rows
FROM public.project_events e
JOIN public.projects p ON p.id = e.project_id
WHERE p.name='${PROJ_ESC}'
  AND e.event_type ILIKE 'Availability%'
  AND e.requested_at::date = DATE '${PLAN_DATE}';
SQL
)
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "$VERIFY_SQL"

echo "[3/4] Re-syncing Postgres sources for collection '${COLLECTION}' ..."

# If explicit IDs provided, use them; else trigger all Postgres sources in the collection
if [[ -n "${EVENTS_SOURCE_ID:-}" || -n "${DELIV_SOURCE_ID:-}" ]]; then
  for SID in ${EVENTS_SOURCE_ID:-} ${DELIV_SOURCE_ID:-}; do
    [[ -n "$SID" ]] || continue
    echo "  - Triggering source $SID"
    curl -s -X POST "${API_URL}/source-connections/${SID}/run" >/dev/null || true
  done
else
  echo "  - Discovering PostgreSQL sources and triggering runs"
  curl -s "${API_URL}/source-connections?collection=${COLLECTION}" \
    | jq -r '.[] | select(.short_name=="postgresql") | .id' \
    | while read -r SID; do
        [[ -n "$SID" ]] || continue
        echo "    • run $SID"
        curl -s -X POST "${API_URL}/source-connections/${SID}/run" >/dev/null || true
      done
fi

echo "[4/4] UI prompts (copy/paste into the UI)"
cat <<PROMPTS

— Reassignment Plan (Generate Answer: ON; Retrieval: Hybrid; Expansion/Rerank/Interpret: OFF/ON/OFF; Filter: {}):

Alice called in sick for ${PROJECT} on ${PLAN_DATE}. We must still deliver the CSV export due ${DUE_DATE}. Propose a 1-day reassignment plan with owners (BE/FE/QA/SRE/PM), concrete tasks, and risks. End with [[1]].

— Evidence Only (Generate Answer: OFF; Retrieval: Hybrid; Filter: {}):

Availability for ${PROJECT} on ${PLAN_DATE}. [[1]]

PROMPTS

echo "Done. Give the sync ~30–60s, then run the prompt in the UI."
