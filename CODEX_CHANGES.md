Summary
- Point Airweave containers to your existing WSL2 Postgres for the internal DB and disable Temporal for a simpler setup.
- Avoid host port clashes by not exposing the bundled Postgres service.

Files Changed
- Added: docker/wsl-host-postgres.override.yml
  - Disables host port binding for the bundled Postgres service (prevents 5432 clash).
  - Sets backend (and temporal-worker) to connect to host Postgres via `host.docker.internal:5432`.
  - Adds `extra_hosts: ["host.docker.internal:host-gateway"]` to ensure name resolution on WSL2/Docker Desktop.
  - Sets `POSTGRES_SSLMODE=disable`.
  - Disables Temporal services by default using profiles (`temporal`, `temporal-ui`, `temporal-worker`).

- Updated: .env
  - `POSTGRES_HOST=host.docker.internal`
  - `POSTGRES_PORT=5432`
  - `POSTGRES_USER=postgres`
  - `POSTGRES_PASSWORD=smederevo026`
  - `POSTGRES_DB=airweave`
  - `POSTGRES_SSLMODE=disable`
  - `TEMPORAL_ENABLED=false`

How To Run
1) Ensure the internal DB exists on your WSL2 Postgres (run once):
   - `psql -U postgres -h localhost -p 5432 -d postgres -c "CREATE DATABASE airweave OWNER postgres;"`
2) Start with the override:
   - `./start.sh --compose-override docker/wsl-host-postgres.override.yml`
   - Backend will run migrations into the `airweave` database on your WSL instance.

Add Your App DB As A Source
- In the UI (http://localhost:8080):
  - Add source → PostgreSQL
  - host: `host.docker.internal`, port: `5432`
  - database: `postgres`
  - user: `postgres`, password: `smederevo026`
  - schema: `public`
  - select tables and views to index
  - set cursor fields for incremental sync if available (e.g., `updated_at`).

Re‑enable Temporal (optional, later)
- Start with Temporal profile enabled:
  - `docker compose -f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml --profile temporal up -d`
- Or flip `TEMPORAL_ENABLED=true` in `.env` and adjust services as needed.

Notes
- Security: `.env` contains plaintext credentials for local dev. Rotate the password later and consider a dedicated role (e.g., `airweave` user) for production-like setups.
- The override does not delete any services; it only changes networking and disables Temporal by default.
- No application code was changed; only deployment configuration and environment values.

Compose Postgres binding
- To avoid clashes with host Postgres on 5432, the bundled Postgres in `docker/docker-compose.yml` now binds to host port 5433 (`5433:5432`).
- The backend still points to your WSL Postgres via `.env` (`host.docker.internal`). The bundled Postgres container is optional and unused unless you reconfigure `.env` to target it.

Rollback
- To revert to the original behavior, remove the override from the startup command and restore the original `.env` values for `POSTGRES_*` and `TEMPORAL_ENABLED`.
