SHELL := /bin/bash

# ---- Defaults (override with VAR=value) --------------------------------------
HOST            ?= localhost
HOST_PG_PORT    ?= 5432
PG_USER         ?= postgres
PG_DB           ?= airweave
API_URL         ?= http://localhost:8001
COLLECTION      ?= helloworld-e4fh2w
COMPOSE         ?= docker compose -f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml
PROJECT         ?= BigCompany
PROMPT_DATE     ?= today

# Optional: set PGPASSWORD in your env if your host Postgres requires it

.PHONY: help seed-db seed-actions apply-constraints apply-deliverables simulate-day \
        build-backend backend-reload worker-reload reload health \
        list-sources resync eod-curl eod-curl-rows ui-eod ui-eod-rows \
        eod-export eod-export-rows simulate-and-export ui-tests

help:
	@echo "Targets:"
	@echo "  seed-db           - Create demo tables and seed events (host Postgres)"
	@echo "  seed-actions      - Create actions/decisions tables + views"
	@echo "  apply-constraints - Create work_plans table + constraints view"
	@echo "  apply-deliverables- Create unified EOD deliverables view"
	@echo "  simulate-day      - Run Observe→Plan→Act→Log SQL for today"
	@echo "  build-backend     - Build backend image locally (no remote pull)"
	@echo "  backend-reload    - Recreate backend container to pick up env/code"
	@echo "  worker-reload     - Recreate temporal-worker container"
	@echo "  reload            - backend-reload + worker-reload"
	@echo "  health            - Check backend health"
	@echo "  list-sources      - List source connection IDs for collection=$(COLLECTION)"
	@echo "  resync            - Re-sync a source (requires CONS_SOURCE_ID=<id>)"
	@echo "  eod-curl          - Sanity EOD query (completion with [[1]])"
	@echo "  eod-curl-rows     - Retrieval-only rows for debugging"
	@echo "  simulate-and-export- Simulate today, re-sync, export EOD"
	@echo "  ui-tests          - Run Section 7 scenarios and save Markdown"

seed-db:
	psql -h $(HOST) -p $(HOST_PG_PORT) -U $(PG_USER) -d $(PG_DB) -f sql/seed_semantic_demo.sql
	psql -h $(HOST) -p $(HOST_PG_PORT) -U $(PG_USER) -d $(PG_DB) -f sql/seed_project_events.sql
	psql -h $(HOST) -p $(HOST_PG_PORT) -U $(PG_USER) -d $(PG_DB) -f sql/add_today_events.sql

seed-actions:
	psql -h $(HOST) -p $(HOST_PG_PORT) -U $(PG_USER) -d $(PG_DB) -f sql/seed_actions.sql

apply-constraints:
	psql -h $(HOST) -p $(HOST_PG_PORT) -U $(PG_USER) -d $(PG_DB) -f sql/constraints.sql

apply-deliverables:
	psql -h $(HOST) -p $(HOST_PG_PORT) -U $(PG_USER) -d $(PG_DB) -f sql/deliverables.sql

simulate-day:
	psql -h $(HOST) -p $(HOST_PG_PORT) -U $(PG_USER) -d $(PG_DB) -f sql/simulate_day.sql

build-backend:
	docker build -t ghcr.io/airweave-ai/airweave-backend:latest -f backend/Dockerfile backend

backend-reload:
	$(COMPOSE) up -d --no-deps --force-recreate --pull=never backend

worker-reload:
	$(COMPOSE) up -d --no-deps --force-recreate --pull=never temporal-worker

reload: backend-reload worker-reload

health:
	@curl -sf $(API_URL)/health && echo " backend OK" || (echo " backend down" && false)

list-sources:
	@curl -s '$(API_URL)/source-connections?collection=$(COLLECTION)' | jq '.[] | {id,name,short_name}'

resync:
	@test -n "$$CONS_SOURCE_ID" || (echo "CONS_SOURCE_ID is required" && false)
	@curl -s -X POST "$(API_URL)/source-connections/$$CONS_SOURCE_ID/run" && echo

eod-curl:
	@curl -s -X POST '$(API_URL)/collections/$(COLLECTION)/search' \
	  -H 'Content-Type: application/json' \
	  --data @- <<'JSON' | jq -r '.completion // .message // .'
		{
		  "query": "Open change requests for BigCompany today. End with [[1]].",
		  "retrieval_strategy": "hybrid",
		  "generate_answer": true,
		  "expand_query": false,
		  "interpret_filters": false,
		  "rerank": true,
		  "filter": {
		    "must": [
		      {"key": "table_name", "match": {"value": "project_event_history_text"}},
		      {"key": "project_name", "match": {"value": "BigCompany"}},
		      {"key": "status", "match": {"value": "Open"}}
		    ]
		  }
		}
	JSON

eod-curl-rows:
	@curl -s -X POST '$(API_URL)/collections/$(COLLECTION)/search' \
	  -H 'Content-Type: application/json' \
	  --data @- <<'JSON' | jq
		{
		  "query": "End-of-day summary for BigCompany (today)",
		  "retrieval_strategy": "hybrid",
		  "generate_answer": false,
		  "expand_query": false,
		  "interpret_filters": false,
		  "rerank": true,
		  "filter": {"must": [{"key": "project_name", "match": {"value": "BigCompany"}}]}
		}
	JSON

eod-export:
	@env \
	  PROJECT="$(PROJECT)" \
	  PROMPT_DATE="$(PROMPT_DATE)" \
	  API_URL="$(API_URL)" \
	  COLLECTION="$(COLLECTION)" \
	  bash scripts/eod_export.sh

eod-export-rows:
	@env \
	  PROJECT="$(PROJECT)" \
	  PROMPT_DATE="$(PROMPT_DATE)" \
	  API_URL="$(API_URL)" \
	  COLLECTION="$(COLLECTION)" \
	  ROWS_ONLY=true \
	  bash scripts/eod_export.sh

	simulate-and-export:
		@env \
	  API_URL="$(API_URL)" \
	  COLLECTION="$(COLLECTION)" \
	  PG_HOST="$(HOST)" \
	  PG_PORT="$(HOST_PG_PORT)" \
	  PG_USER="$(PG_USER)" \
	  PG_DB="$(PG_DB)" \
	  PROJECT="$(PROJECT)" \
	  PROMPT_DATE="$(PROMPT_DATE)" \
	  ACTIONS_SOURCE_ID="$(ACTIONS_SOURCE_ID)" \
	  DELIV_SOURCE_ID="$(DELIV_SOURCE_ID)" \
	  bash scripts/simulate_and_export.sh

# Print a ready-to-paste UI request body (completion with concise reasoning)
ui-eod:
		@cat <<JSON
		{
		  "query": "End-of-day summary for $(PROJECT) for $(PROMPT_DATE): list today’s events (incident, new lead, sick leave), actions taken (moves, assignments, emails), and rationale. Then add a section titled \"Model Reasoning (concise)\" with 3–5 short bullets explaining key signals from the retrieved rows, stated as verifiable justifications (no hidden chain-of-thought). Include assumptions, tradeoffs, and a one-line confidence. End with [[1]].",
		  "retrieval_strategy": "hybrid",
		  "generate_answer": true,
		  "expand_query": false,
		  "interpret_filters": false,
		  "rerank": true,
		  "filter": {
		    "must": [
		      {"key": "project_name", "match": {"value": "$(PROJECT)"}}
		    ]
		  }
		}
		JSON

# Print a retrieval-only body to inspect rows in the UI
ui-eod-rows:
		@cat <<JSON
		{
		  "query": "End-of-day summary for $(PROJECT) ($(PROMPT_DATE))",
		  "retrieval_strategy": "hybrid",
		  "generate_answer": false,
		  "expand_query": false,
		  "interpret_filters": false,
		  "rerank": true,
		  "filter": {
		    "must": [
		      {"key": "project_name", "match": {"value": "$(PROJECT)"}}
		    ]
		  }
		}
		JSON

ui-tests:
	@env \
	  API_URL="$(API_URL)" \
	  COLLECTION="$(COLLECTION)" \
	  PROJECT="$(PROJECT)" \
	  PROMPT_DATE="$(PROMPT_DATE)" \
	  OUTDIR="$(OUTDIR)" \
	  bash scripts/ui_test_suite.sh

.PHONY: sick-leave
sick-leave:
	@env \
	  API_URL="$(API_URL)" \
	  COLLECTION="$(COLLECTION)" \
	  PG_HOST="$(HOST)" \
	  PG_PORT="$(HOST_PG_PORT)" \
	  PG_USER="$(PG_USER)" \
	  PG_DB="$(PG_DB)" \
	  PROJECT="$(PROJECT)" \
	  PLAN_DATE="$(PROMPT_DATE)" \
	  DUE_DATE="$(DUE_DATE)" \
	  bash scripts/sick_leave_and_resync.sh
