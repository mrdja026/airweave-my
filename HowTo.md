Local Setup Guide (WSL2 + Docker Desktop + Host Postgres)

Use this guide to run Airweave locally on Windows with WSL2, connecting the containers to a Postgres instance running in WSL. This avoids port conflicts and skips pulling private GHCR images by building locally.

Prerequisites
- Docker Desktop installed with WSL2 integration enabled
- Postgres running in WSL2, listening on 0.0.0.0:5432 (no SSL)
- Optional tools: psql, curl, jq

One‑Time Setup
1) Create the internal Airweave database in your WSL2 Postgres
   - psql -U postgres -h localhost -p 5432 -d postgres -c "CREATE DATABASE airweave OWNER postgres;"

2) Verify environment variables (.env)
   - .env should contain:
     - POSTGRES_HOST=host.docker.internal
     - POSTGRES_PORT=5432
     - POSTGRES_USER=postgres
     - POSTGRES_PASSWORD=YOUR_PASSWORD
     - POSTGRES_DB=airweave
     - POSTGRES_SSLMODE=disable
     - TEMPORAL_ENABLED=false
   - Note: Only .env is used at runtime. .env.example is not read by Docker.

3) Build local Docker images (avoid GHCR pulls)
   - docker build -t airweave-backend:local ./backend
   - docker build -t airweave-frontend:local ./frontend

Start Services (Dashboard + API)
Preferred: start.sh with WSL override and local images
- BACKEND_IMAGE=airweave-backend:local FRONTEND_IMAGE=airweave-frontend:local ./start.sh --wsl-override

Alternative: start via docker compose directly
- export BACKEND_IMAGE=airweave-backend:local
- export FRONTEND_IMAGE=airweave-frontend:local
- docker compose -f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml up -d

What the override does
- Disables binding the bundled Postgres on host 5432 (no port clash)
- Points backend to your WSL Postgres via host.docker.internal:5432
- Adds extra_hosts for reliable name resolution on WSL2
- Disables Temporal by default (can re-enable later)

Verify Services
- API health: curl -sSf http://localhost:8001/health
- UI: http://localhost:8080
- Swagger: http://localhost:8001/docs

start.sh flags you can use
- `--wsl-override`: include `docker/wsl-host-postgres.override.yml` automatically (routes backend to WSL Postgres on 5432, sets extra_hosts, enables Temporal).
- `--skip-local-embeddings`: do not start the `text2vec-transformers` service.
- `--skip-frontend`: start backend only (no UI).
- `--noninteractive`: skip interactive prompts for API keys.
- `--backend-only`: same as `--skip-frontend` (backend + dependencies only).
- `--frontend-only`: start frontend (and backend) but skip local embeddings for a lighter startup.
- `--with-local-embeddings`: force local embeddings ON even if `OPENAI_API_KEY` is set.

Enable Local Embeddings (for offline neural/hybrid search)
- Start the local transformers inference container (384‑dim MiniLM) so search can embed queries without cloud keys:
  - docker compose -f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml --profile local-embeddings up -d text2vec-transformers
- TEXT2VEC_INFERENCE_URL is already set to http://localhost:9878 in .env; backend will use it.

Use Ollama For Answers (optional, fully local RAG)
- Ensure Ollama runs on Windows host (e.g., http://localhost:11434) and your model is pulled (e.g., gemma:7b).
- In .env, set:
  - OLLAMA_BASE_URL=http://host.docker.internal:11434
  - OLLAMA_MODEL=gemma:7b
- The backend will prefer Ollama for answer generation when present. Expansion/Interpretation/Rerank remain off by default for offline mode.

Index Your Existing Postgres (as a Source)
Using the UI
- In the dashboard, create a collection (e.g., “app-data”).
- Add source → PostgreSQL with:
  - host: host.docker.internal, port: 5432
  - database: postgres (your app DB)
  - user: postgres, password: YOUR_PASSWORD
  - schema: public
  - tables: * (or select specific tables/views)
- Save and Run Sync, then search within the collection.

Using the API (optional)
1) Create a collection
   - curl -sS -X POST http://localhost:8001/collections/ \
     -H "Content-Type: application/json" \
     -d '{"name":"app-data"}'

2) Create a PostgreSQL source connection (replace READABLE with your collection readable_id)
   - curl -sS -X POST http://localhost:8001/source-connections/ \
     -H "Content-Type: application/json" \
     -d '{
           "name": "postgres-app",
           "short_name": "postgresql",
           "readable_collection_id": "READABLE",
           "sync_immediately": true,
           "authentication": {
             "credentials": {
               "host": "host.docker.internal",
               "port": 5432,
               "database": "postgres",
               "user": "postgres",
               "password": "YOUR_PASSWORD",
               "schema": "public",
               "tables": "*"
             }
           }
         }'

3) Search the collection (offline-friendly config)
   - curl -sS -X POST http://localhost:8001/collections/READABLE/search \
     -H "Content-Type: application/json" \
     -d '{"query":"hello", "retrieval_strategy":"hybrid", "generate_answer": true, "expand_query": false, "interpret_filters": false, "rerank": false}'

Re‑enable Temporal (optional, later)
- docker compose -f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml --profile temporal up -d
- Or set TEMPORAL_ENABLED=true in .env and adjust as needed.

Troubleshooting
- GHCR denied: Build images locally as shown above and pass BACKEND_IMAGE/FRONTEND_IMAGE.
- host.docker.internal not reachable: Use the WSL eth0 IP for POSTGRES_HOST in .env:
  - ip -4 addr show eth0 | sed -n 's/.*inet \([0-9.]*\).*/\1/p'
  - Update .env → POSTGRES_HOST=<that IP>, then restart.
- Port 5432 already in use:
  - Default (Option A): We do not expose the bundled Postgres; start only required services.
  - Option B: We rebind the bundled Postgres to host port 5433 via the override. Connect to it using port 5433.
    - Note: In this guide, backend uses your WSL Postgres (not the bundled one). The bundled container is optional and unused unless you point .env to it.

Setup: External Postgres Source + Temporal (What We Did & Why)

Goal
- Use your existing Postgres (WSL2) both as:
  - Internal DB for Airweave state (database: `airweave`)
  - External source DB to index/search (database: `postgres`, schema `public`)
- Keep your current Postgres UI and ports unchanged.

What we changed
- `.env`: Point backend to your WSL Postgres for internal state and enable Temporal
  - `POSTGRES_HOST=host.docker.internal` (fallback to WSL eth0 IP if needed)
  - `POSTGRES_PORT=5432`, `POSTGRES_DB=airweave`, `POSTGRES_SSLMODE=disable`
  - `TEMPORAL_ENABLED=true`
- `docker/docker-compose.yml`: Rebound bundled Postgres to host port `5433:5432` to avoid clashing with WSL `5432`.
- `docker/wsl-host-postgres.override.yml`:
  - Ensure backend uses `host.docker.internal` for Postgres
  - Start Temporal services by default (no `--profile` support needed)
  - Keep Redis/Qdrant dependencies; backend no longer depends_on bundled Postgres
- Built local images to avoid GHCR pulls: `airweave-backend:local`, `airweave-frontend:local`.

Why these changes were needed
- Port conflict on 5432: Your WSL Postgres already binds 5432. The bundled container originally attempted `5432:5432`. Rebinding to `5433:5432` (or not starting it) prevents conflicts while preserving your WSL instance.
- GHCR registry denied: Building local images avoids needing access to GHCR and speeds iteration.
- host.docker.internal caveat: On Windows+WSL2, containers typically reach the host via `host.docker.internal`. If DNS fails, use the WSL eth0 IP instead.
- Temporal disabled caused 500s: The UI creates schedules/continuous runs that talk to Temporal. With Temporal off, backend tried to contact Temporal and failed DNS, returning 500. Enabling Temporal restores the UI’s default create+run flow.
- Broken refresh_all in this snapshot: The `collections/refresh_all` endpoint referenced a missing helper. With Temporal enabled, you can rely on the normal, scheduled/run flow instead of that endpoint.

Startup with Temporal (final working flow)
- Build local images once:
  - `docker build -t airweave-backend:local ./backend`
  - `docker build -t airweave-frontend:local ./frontend`
- Ensure internal DB exists on WSL Postgres:
  - `psql -U postgres -h localhost -p 5432 -d postgres -c "CREATE DATABASE airweave OWNER postgres;"`
- Start services with the WSL override (Temporal auto-starts):
  - `BACKEND_IMAGE=airweave-backend:local FRONTEND_IMAGE=airweave-frontend:local ./start.sh --wsl-override`
- Verify:
  - API: `http://localhost:8001/health`
  - UI: `http://localhost:8080`
  - Temporal UI: `http://localhost:8088`

Add the external Postgres source (UI)
- Create a collection (e.g., “hello-world”).
- Add source → PostgreSQL with:
  - Host: `host.docker.internal` (or WSL eth0 IP)
  - Port: `5432`
  - Database: `postgres`
  - Username: `postgres`, Password: `your password`
  - Schema: `public`, Tables: `*` (or select specific tables/views)
- Keep the schedule if you want periodic runs. Click Run to trigger via Temporal.

Smoke test (API)
- Search: `curl -sS -X POST http://localhost:8001/collections/<readable_id>/search -H 'Content-Type: application/json' -d '{"query":"hello", "retrieval_strategy":"hybrid", "generate_answer": true, "expand_query": false, "interpret_filters": false, "rerank": false}'`

Reminders for future you
- If source creation fails with a DNS/Temporal error in UI, ensure Temporal is enabled and reachable (compose starts `temporal` + `temporal-ui` + worker; `TEMPORAL_HOST=temporal`).
- If DB connect fails: replace `host.docker.internal` with the WSL eth0 IP in the source form.
- If 5432 binds conflict: confirm the bundled Postgres is on `5433:5432` (override) and that you started with the override.
- If GHCR pulls fail: always build/run local images as shown above.
 - If search complains about providers/keys: ensure the `text2vec-transformers` container is running (for embeddings) and, if using answers, that `OLLAMA_BASE_URL` points to your host and the model exists.

Security Notes
- Do not commit real passwords to version control. .env is for local dev only; rotate credentials later.

Change Log
- See CODEX_CHANGES.md for what was added/updated and rollback instructions.
