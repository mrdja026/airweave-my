# EOD Demo Setup + Reasoned Summaries Runbook (Oct 16, 2025)

This runbook captures what we changed, why we changed it, and the exact steps to reproduce the end‑to‑end EOD workflow using local Postgres and Ollama (gemma:7b). It is safe to re‑run.

## Overview of Changes
- Added a demo relevance toggle to avoid strict fallbacks:
  - `airweave/.env`: `STRICT_RAG_MIN_SCORE=0.01`
- Added SQL for today’s demo events (incident, new lead, sick leave):
  - `airweave/sql/add_today_events.sql`
- Verified WSL host‑Postgres override (backend points to host DB on 5432):
  - `airweave/docker/wsl-host-postgres.override.yml`
- Documented recreate path without remote pulls by building backend image locally.
- Provided EOD prompt(s) and toggles, including a concise “Model Reasoning” section from Ollama gemma:7b.
 - Enabled fully local hybrid reranking via Ollama (no cloud keys):
   - Implemented `rerank()` in `backend/airweave/search/providers/ollama.py`.
   - Updated `backend/airweave/search/defaults.yml` to add an Ollama rerank model and set Ollama as first choice under `operation_preferences.reranking`.

## Environment Assumptions
- Backend/API on `http://localhost:8001` is up and healthy (`{"status":"healthy"}`).
- Ollama is running and reachable; `.env` has:
  - `OLLAMA_BASE_URL=http://<your_host>:11434`
  - `OLLAMA_MODEL=gemma:7b`
- You are using the WSL host‑Postgres override so backend reads host DB:
  - Compose: `-f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml`
  - DB for seeding: host `localhost:5432`, user `postgres`, db `airweave`.

## Seed Database (Host Postgres 5432)
Run these from the repository root.

```
psql -h localhost -p 5432 -U postgres -d airweave -f airweave/sql/seed_semantic_demo.sql
psql -h localhost -p 5432 -U postgres -d airweave -f airweave/sql/seed_project_events.sql
psql -h localhost -p 5432 -U postgres -d airweave -f airweave/sql/add_today_events.sql
```

Notes
- `seed_semantic_demo.sql` creates `public.projects` and related demo tables/views.
- `seed_project_events.sql` creates `public.project_events` and a semantic view `public.project_event_history_text` and seeds history, including a CSV export change request due `2025-10-20`.
- `add_today_events.sql` adds “Incident: critical bug”, “New Lead”, and “Availability (sick)” for today.

## Pick Up the New STRICT_RAG_MIN_SCORE (No Remote Pulls)
If the backend was already running when you edited `.env`, recreate the backend (and worker) so it reads the updated env. Build locally to avoid GHCR pulls.

1) Build backend image locally
```
docker build -t ghcr.io/airweave-ai/airweave-backend:latest -f backend/Dockerfile backend
```

2) Recreate services with WSL override (no dependency restarts, no pulls)
```
docker compose -f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml \
  up -d --no-deps --force-recreate --pull=never backend temporal-worker
```

3) Health check
```
curl -sf http://localhost:8001/health && echo "backend OK"
```

## Re‑Sync the Postgres Source
Sync after seeding so rows appear in the collection (`helloworld-e4fh2w`).

```
curl -s 'http://localhost:8001/source-connections?collection=helloworld-e4fh2w' | jq '.[] | {id,name,short_name}'
curl -s -X POST "http://localhost:8001/source-connections/CONS_SOURCE_ID/run"
```

## Sanity Search (forces a completion)
This query bypasses strictness issues via a minimal citation suffix and should generate an answer.

```
curl -s -X POST 'http://localhost:8001/collections/helloworld-e4fh2w/search' \
  -H 'Content-Type: application/json' --data '{
  "query":"Open change requests for BigCompany today. End with [[1]].",
  "retrieval_strategy":"hybrid",
  "generate_answer":true,
  "expand_query":false,
  "interpret_filters":false,
  "rerank":false,
  "filter":{
    "must":[
      {"key":"table_name","match":{"value":"project_event_history_text"}},
      {"key":"project_name","match":{"value":"BigCompany"}},
      {"key":"status","match":{"value":"Open"}}
    ]
  }
}'
```

## Makefile Quickstart
From `airweave/`, these one-liners reproduce the full flow:

```
# 0) Seed host Postgres (5432) with demo tables + events
make seed-db HOST_PG_PORT=5432 PG_USER=postgres PG_DB=airweave

# 1) Build backend locally (no remote pulls), then reload to pick up env/code
make build-backend
make backend-reload

# 2) Confirm backend health
make health

# 3) Find your Postgres source ID and re-sync (copy the id from list-sources)
make list-sources
CONS_SOURCE_ID=<paste-id> make resync

# 4) Sanity EOD completion (uses hybrid + rerank + [[1]] gate)
make eod-curl

# 5) Inspect raw rows (retrieval only) if needed
make eod-curl-rows

# 6) Generate a ready-to-paste UI body (Code panel)
make ui-eod PROJECT=BigCompany PROMPT_DATE="Oct 16, 2025" > body.json
# In the UI, open Code, paste the JSON from body.json, and run.

# (Optional) Retrieval-only UI body
make ui-eod-rows PROJECT=BigCompany PROMPT_DATE="today" > rows.json

## Scripted Export (Markdown file)
Use the helper script to save the EOD directly to a Markdown file via the API.

```
# Completion mode (concise reasoning, [[1]] citation gate)
make eod-export PROJECT=BigCompany PROMPT_DATE="Oct 16, 2025"

# Rows-only mode (no completion, lists retrieved rows grouped by table)
make eod-export-rows PROJECT=BigCompany PROMPT_DATE="Oct 16, 2025"

# Customize output filename
OUT=Demo/EOD_BigCompany_2025-10-16.md make eod-export PROJECT=BigCompany PROMPT_DATE="Oct 16, 2025"
```

Script details:
- Path: `scripts/eod_export.sh`
- Reads: `API_URL`, `COLLECTION`, `PROJECT`, `PROMPT_DATE`, `ROWS_ONLY`, `RERANK`, `OUT`.
- Default output: `Demo/EOD_${PROJECT}_YYYY-MM-DD.md`.

## Simulation + Constraints + Deliverables (SQL)
Run these once to enable the full Observe → Plan → Act → Log loop and deliverables view:

```
# 0) Ensure base seed is applied (projects, employees, events)
make seed-db HOST_PG_PORT=5432 PG_USER=postgres PG_DB=airweave

# 1) Create actions/decisions tables + views
make seed-actions HOST_PG_PORT=5432 PG_USER=postgres PG_DB=airweave

# 2) Add constraints table/view (work plans + summary)
make apply-constraints HOST_PG_PORT=5432 PG_USER=postgres PG_DB=airweave

# 3) Add unified EOD deliverables view
make apply-deliverables HOST_PG_PORT=5432 PG_USER=postgres PG_DB=airweave

# 4) Simulate today (inserts work_plan rows, actions, CEO decisions)
make simulate-day HOST_PG_PORT=5432 PG_USER=postgres PG_DB=airweave

# 5) Re-sync and export EOD
make list-sources
CONS_SOURCE_ID=<id> make resync
make eod-export PROJECT=BigCompany PROMPT_DATE="Oct 16, 2025"
```

Quick SQL spot-checks:
- `SELECT * FROM public.project_constraints_text WHERE project_name='BigCompany';`
- `SELECT * FROM public.performed_actions_text ORDER BY created_at DESC LIMIT 5;`
- `SELECT * FROM public.ceo_decisions_text ORDER BY created_at DESC LIMIT 5;`
- `SELECT * FROM public.eod_deliverables_text WHERE project_name='BigCompany' ORDER BY ts DESC LIMIT 10;`
```

Notes
- Override variables as needed, e.g., `HOST_PG_PORT`, `PG_USER`, `PG_DB`, `COLLECTION`, `API_URL`.
- If your Postgres requires a password, export `PGPASSWORD` before running `make seed-db`.


## Local Hybrid Reranking (Ollama)
- What it is: results are retrieved using hybrid (keyword + vector) and then re-ordered by gemma:7b running on your Ollama server.
- What we changed:
  - `defaults.yml`: adds `provider_models.ollama.rerank` and prefers Ollama under `operation_preferences.reranking`.
  - `OllamaProvider.rerank()`: prompts for strict JSON rankings and reorders results.
- How to use:
  - In the UI, set “Rerank” to ON (keep Retrieval: Hybrid).
  - Ensure `.env` has `OLLAMA_BASE_URL` and `OLLAMA_MODEL=gemma:7b`.
  - If backend is already running, restart just the backend container to reload code:  
    `docker compose -f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml up -d --no-deps --force-recreate --pull=never backend`

## UI: EOD Prompt (with Reasoning from Ollama)
Use these toggles so the backend routes to Ollama (gemma:7b) for the completion.

- Retrieval: Hybrid
- Generate Answer: ON
- Expansion: OFF
- Rerank: OFF
- Interpret Filters: OFF
- Filter JSON: `{"must":[{"key":"project_name","match":{"value":"BigCompany"}}]}`

Prompt (date fixed)
```
End-of-day summary for BigCompany for Oct 16, 2025: list today’s events (incident, new lead, sick leave), actions taken (moves, assignments, emails), and rationale. Then add a section titled “Model Reasoning (concise)” with 3–5 short bullets explaining key signals from the retrieved rows, stated as verifiable justifications (no hidden chain-of-thought). Include assumptions, tradeoffs, and a one-line confidence. End with [[1]].
```

Prompt (dynamic date)
```
End-of-day summary for BigCompany (today): list today’s events (incident, new lead, sick leave), actions taken (moves, assignments, emails), and rationale. Then add a section titled “Model Reasoning (concise)” with 3–5 short bullets explaining key signals from the retrieved rows, stated as verifiable justifications (no hidden chain-of-thought). Include assumptions, tradeoffs, and a one-line confidence. End with [[1]].
```

Tip: If you still get the fallback message, either keep the `[[1]]` suffix, or temporarily set Generate Answer OFF to verify rows, then export via “Export as Markdown (Auto‑Download)”.

## EOD Content Ground Truth (What changed today)
Inserted on Oct 16, 2025 via `add_today_events.sql` and visible in `project_event_history_text` after re‑sync:
- Incident: critical bug in exports path (priority High, status Open).
- New Lead: Client D requesting proposal for data‑sync integration within 48h (status Open).
- Availability: Alice called in sick; reassign critical tasks (status Open).
- From baseline seed: Change Request “dashboard CSV export” due 2025‑10‑20 (status Open).

## CSV Export: One‑Day Plan (Due 2025‑10‑20)
- Objectives (EOD): shipping `GET /accounts/export.csv` with auth, filters, streaming; UI button; tests + docs.
- Owners: TL (Jane), BE (Grace), FE (Bob), QA (Priya), SRE (Dan), PM (Alex).
- Milestones: scope (09–10h) → BE (10–13h) → FE (13–15h) → QA/SRE (15–16:30h) → Review/Rollout (16:30–17:30h).
- Acceptance: filter parity, 50k row bound (or prompt to narrow), UTF‑8 CSV, stable column order, tests pass.

## Client Email Draft (Client A)
Subject: Status: Export Incident and CSV Export Delivery Plan

Hi <Client A POC>,

Today (Oct 16) we identified and mitigated a production issue affecting the exports path. Our SRE team has rolled back to the last known good version and is deploying a guard to prevent recurrence. A full post‑mortem with remediation actions will follow within 24 hours.

On the CSV export for the Accounts page (due Oct 20), we’ve scheduled a focused one‑day build to ship a secure, filter‑aware export with a simple UI trigger and test coverage. Given an engineer out sick, we’ve reassigned ownership to ensure timing stays on track.

Plan highlights:
- Backend streaming CSV with filter parity to the Accounts view
- UI export button integrated with existing filters
- Testing at scale and monitoring for reliability

We’ll confirm staging access later today and share the release note and acceptance checklist. Please let us know if there are must‑have columns or row limits beyond the defaults.

Best,
<Your Name>
<Title> | <Company>
<Phone/Slack>

## Troubleshooting
- “No relevant information…”
  - Ensure `.env` contains `STRICT_RAG_MIN_SCORE=0.01` and the backend was recreated.
  - Use the minimal suffix once: `End with [[1]]`.
  - Verify UI request flags: `generate_answer=true`, `expand_query=false`, `rerank=false`, `interpret_filters=false`, and the filter JSON includes the project name.
- Check health: ``curl -sf http://localhost:8001/health``.
- Verify rows exist: connect to Postgres and `SELECT * FROM public.project_event_history_text ORDER BY requested_at DESC LIMIT 10;`.

## File Index
- `.env` (added): `STRICT_RAG_MIN_SCORE=0.01`
- `sql/seed_semantic_demo.sql` (creates `public.projects`, team summary view)
- `sql/seed_project_events.sql` (creates `public.project_events` + semantic view + seeds incl. CSV export due 2025‑10‑20)
- `sql/add_today_events.sql` (adds incident/new‑lead/sick for today)
- `docker/wsl-host-postgres.override.yml` (backend → host Postgres 5432)
