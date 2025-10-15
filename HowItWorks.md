# Airweave Local RAG – How It Works

This document explains the components used and the end‑to‑end flow for a fully local, no‑cloud‑keys RAG setup with Airweave. It also lists the retrieval math, data paths, and how to run/troubleshoot.

## Components

- Backend API (FastAPI)
  - Orchestrates search and RAG pipeline.
  - Endpoints: `/collections/{readable_id}/search` and `/search/stream`.
- Source: PostgreSQL
  - Connects to your WSL Postgres (e.g., host.docker.internal:5432, db `postgres`).
  - Extracts rows and writes chunked entities for indexing.
- Sync Engine + Temporal
  - Schedules and runs sync jobs (initial + incremental).
  - Writes entities and vectors to Qdrant.
- Embeddings (index‑time & query‑time): Local Text2Vec
  - Service: `semitechnologies/transformers-inference` on `TEXT2VEC_INFERENCE_URL` (default `http://localhost:9878`).
  - Dimensions: 384 (MiniLM‑L6‑v2). No cloud keys required.
- Sparse keyword model: BM25 (local)
  - Generates sparse embeddings for keyword search (fastembed under the hood).
- Vector DB: Qdrant
  - Dense vectors: 384‑dim, cosine distance.
  - Sparse vectors: BM25 IDF index.
  - Shared physical collections, tenant isolation via `airweave_collection_id` payload.
- LLM (answers): Ollama
  - `OLLAMA_BASE_URL` (e.g., `http://host.docker.internal:11434`) and `OLLAMA_MODEL` (e.g., `gemma:7b`).
  - Used to produce natural‑language answers from retrieved results.
- Frontend (React)
  - Search UI and streaming (SSE). Defaults optimized for offline.
- Auth
  - Disabled locally (`AUTH_ENABLED=false`), so no `X-API-Key` is required for UI or API.

## End‑to‑End Flow

1) Sync/Index
- PostgreSQL → extract rows → chunk & transform → embed (dense 384 + optional BM25 sparse) → upsert into Qdrant.

2) Query
- UI or API sends a query with offline‑friendly toggles.
- EmbedQuery:
  - Dense: Local Text2Vec (384‑dim) at `TEXT2VEC_INFERENCE_URL`.
  - Sparse: BM25 (keyword) locally.
- Retrieval (Qdrant):
  - Mode = hybrid (dense + sparse) or neural (dense only) or keyword (sparse only).
  - Hybrid uses Reciprocal Rank Fusion (RRF) to blend dense and sparse candidates.
  - Optional Temporal Relevance computes a time‑decay formula over `airweave_system_metadata.airweave_updated_at` and blends into scoring.
- Reranking (optional): OFF by default for offline MVP (no cloud provider needed).
- Answer Generation:
  - Ollama (`/api/chat`) summarizes the top results into a coherent answer.

3) Response
- Returns search results plus `completion` (the generated answer) when enabled.

## Retrieval Math

- Dense Similarity: cosine distance over 384‑dim embeddings in Qdrant.
- Sparse Similarity: BM25 (IDF‑weighted) keyword matching in Qdrant’s sparse index.
- Hybrid Fusion: Reciprocal Rank Fusion (RRF) combines dense and sparse ranks.
- Temporal Relevance (optional): Linear/exponential/gaussian decay applied in Qdrant as a formula over the score with a data‑driven time span.

## Offline Defaults (MVP)

- Answer: ON (Ollama)
- Expansion: OFF
- Interpretation: OFF
- Rerank: OFF
- Recency bias: OFF (can be enabled later)
- Retrieval: hybrid (works offline via local dense + BM25 sparse)

These defaults avoid any cloud LLM calls while still providing neural + keyword hybrid retrieval and local answer generation.

## Running Locally

Prereqs
- `.env`: `AUTH_ENABLED=false`, `TEXT2VEC_INFERENCE_URL=http://localhost:9878`.
- Optional for answers: `OLLAMA_BASE_URL=http://host.docker.internal:11434`, `OLLAMA_MODEL=gemma:7b`.
- Build images after code changes:
  ```bash
  docker build -t airweave-backend:local ./backend
  docker build -t airweave-frontend:local ./frontend
  ```
- Start local embeddings service (384‑dim):
  ```bash
  docker compose -f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml \
    --profile local-embeddings up -d text2vec-transformers
  ```
- Bring up the full stack (backend + frontend + embeddings):
  ```bash
  BACKEND_IMAGE=airweave-backend:local FRONTEND_IMAGE=airweave-frontend:local \
  docker compose -f docker/docker-compose.yml -f docker/wsl-host-postgres.override.yml \
    --profile local-embeddings --profile frontend up -d
  ```

Smoke test
- API: `curl -f http://localhost:8001/health`
- UI: open `http://localhost:8080`
- Query (replace READABLE):
  ```bash
  curl -sS -X POST http://localhost:8001/collections/READABLE/search \
    -H 'Content-Type: application/json' \
    -d '{
      "query":"hello from my db",
      "retrieval_strategy":"hybrid",
      "generate_answer": true,
      "expand_query": false,
      "interpret_filters": false,
      "rerank": false
    }'
  ```

## Tuning & Options

- Temporal relevance: enable recency by setting a positive `temporal_relevance` (e.g., 0.3). The service computes a time window from your data and blends it into scoring.
- Retrieval strategy:
  - `hybrid` (recommended offline): dense + BM25 fused by RRF.
  - `neural`: dense only (fastest, still offline).
  - `keyword`: sparse only.
- Answer model: Change `OLLAMA_MODEL` (e.g., `mistral:7b`, `qwen2.5:7b`). Ensure the model is pulled in Ollama on Windows.
- UI toggles: You can later enable Expansion/Interpretation/Rerank once local LLM paths are added; MVP keeps them off.

## Troubleshooting

- “Provider/keys” errors when searching:
  - Ensure `text2vec-transformers` is running on `http://localhost:9878`.
  - If answers enabled, ensure `OLLAMA_BASE_URL` is correct and the model exists (`ollama pull gemma:7b`).
- No results:
  - Confirm the collection sync completed and entity counts > 0.
  - Verify Qdrant reachable: `http://localhost:6333/healthz`.
- Auth/keys prompts:
  - Local dev uses `AUTH_ENABLED=false`; no `X-API-Key` is required.

## Why This Is Fully Offline

- No OpenAI/Mistral/Groq/Cohere keys used.
- Embeddings via local transformer inference.
- Answers via local Ollama.
- Search/retrieval inside Qdrant (local container).

## Next Steps (Optional)

- Local reranking via Ollama (prompt‑based) and/or classical scorers.
- Local query expansion/interpretation via Ollama structured outputs.
- UI selector for Ollama model per collection.

---
This setup mirrors the hosted behavior while removing cloud dependencies, so you can RAG over your Postgres data entirely on your machine.
