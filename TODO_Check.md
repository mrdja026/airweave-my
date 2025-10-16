# TODO_Check: RAG Setup, Hybrid Methods, TVF Design, Multi‑Table Strategy

This note captures decisions, best practices, and checks for the current Airweave setup. It includes links for deeper reading.

---

## Goals
- Use strict, grounded RAG with hybrid retrieval (dense + sparse) and reliable citations.
- Shape upstream data (via TVF/materialized view) to improve recall and precise filtering.
- Search across all relevant tables by default; use metadata filters per task.
- Keep a tunable relevance threshold to avoid hallucinations or off‑topic answers.

---

## Hybrid Retrieval Methods (Beyond “Cosine Only”)
- Sparse lexical retrieval
  - BM25/BM25F: robust for exact terms, IDs, acronyms, numerics.
  - Learned sparse (e.g., SPLADE) for improved term weighting.
- Dense semantic retrieval
  - Embedding similarity (cosine/dot) for meaning‑level matches.
- Score fusion strategies
  - Relative score fusion, ranked fusion, Reciprocal Rank Fusion (RRF) to combine dense + sparse.
- Late‑interaction reranking
  - Cross‑encoders / ColBERT‑style reranking on the top‑K for finer token‑level alignment.

References
- Qdrant: reranking + hybrid pipelines
  - https://qdrant.tech/documentation/search-precision/reranking-hybrid-search/
  - Payload/indexing concepts: https://qdrant.tech/documentation/concepts/indexing/
- Weaviate: hybrid search concepts and fusion knobs
  - https://docs.weaviate.io/weaviate/concepts/search/hybrid-search
- Pinecone: hybrid weighting examples (alpha)
  - https://docs.pinecone.io/docs/hybrid-search
- Microsoft (vendor‑neutral RAG retrieval guidance)
  - https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-information-retrieval

---

## TVF / Materialized View Design for RAG
Design a TVF (or a materialized view) that emits retrieval‑ready rows:

- Columns to emit
  - `entity_id` (stable primary key; used for dedupe and citations)
  - `embeddable_text` (coherent, human‑readable facts for embeddings)
  - Filterable metadata: `table_name`, `entity_type`, `department`, `role`, `project_id`, `rate`, `currency`, `date_*` fields, etc.
  - Optional: `md_content` if you want structured Markdown for display.
- `embeddable_text` guidance
  - One self‑contained sentence or two per row; keep important numbers/units.
  - Example (employees):
    - `"Frank — Senior Developer — rate: 30.0 USD/hour — Dept: Engineering."`
  - Example (timesheets/invoices):
    - `"Invoice INV-104 for Project P-22 — total: 14,500 USD — date: 2025-02-11."`
- Normalize units and dates
  - Choose canonical currency, unit, and date format; add original fields if needed.
- Synonyms/acronyms
  - Add columns or keyword bags for variants ("dev", "developer", "engineer") to help sparse search.
- Keep parent/child linkage
  - Include foreign keys or denormalized identifiers so answers can cite the right row.

Microsoft guidance on index/schema and chunking
- Index/schema design for RAG: https://learn.microsoft.com/en-us/azure/search/tutorial-rag-build-solution-index-schema
- Semantic chunking guidance: https://learn.microsoft.com/en-us/azure/search/search-how-to-semantic-chunking

---

## Multi‑Table Strategy
- Default behavior: search across all tables (no filter) to let hybrid retrieval surface the most relevant facts.
- Task‑scoped filters: apply JSON filters only when the user intent targets a specific entity type/table.
  - Examples
    - Employees only: `{ "must": [{ "key": "table_name", "match": { "value": "employees" } }] }`
    - Or by entity type: `{ "must": [{ "key": "airweave_system_metadata.entity_type", "match": { "value": "EmployeesTableEntity" } }] }`
- Payload indexes
  - Index only fields you frequently filter/sort on (e.g., `table_name`, `entity_type`, `department`, `date`, `project_id`). See Qdrant payload indexing: https://qdrant.tech/documentation/concepts/indexing/

---

## Airweave Config Notes (Strict RAG + UI)
- Strict fallback string enforced by backend
  - If no citations `[[N]]` are present or top score < threshold, backend returns exactly: "No relevant information found in this collection."
- Relevance threshold (tunable)
  - Env: `STRICT_RAG_MIN_SCORE` (default added in code: `0.12`). Increase to be stricter; decrease to be more permissive.
- UI toggles for strict debugging
  - Answer: ON
  - Expansion: OFF
  - Interpretation: OFF
  - Rerank: OFF
  - Filter: optional per task as above

Rebuild + restart
```
# Rebuild backend with latest strict‑RAG changes
docker build -t airweave-backend:local ./backend

# Start with a chosen threshold (example 0.12)
STRICT_RAG_MIN_SCORE=0.12 \
  BACKEND_IMAGE=airweave-backend:local \
  FRONTEND_IMAGE=airweave-frontend:local \
  ./start.sh --wsl-override --with-local-embeddings --noninteractive
```

---

## Verification Checklist
- Negative test (off‑corpus):
  - Query: "Who is the CEO of FooCorp?"
  - Expect: `No relevant information found in this collection.`
- Positive test (employees)
```
curl -N -sS \
  -H 'Accept: text/event-stream' \
  -H 'Content-Type: application/json' \
  -X POST http://localhost:8001/collections/helloworld-e4fh2w/search/stream \
  --data '{
    "query":"Which employee has the highest rate? Return the name and rate.",
    "retrieval_strategy":"hybrid",
    "generate_answer":true,
    "expand_query":false,
    "interpret_filters":false,
    "rerank":false,
    "filter":{"must":[{"key":"table_name","match":{"value":"employees"}}]}
  }'
```
  - Expect concise answer with citation, e.g., `Frank — 30.0 [[N]]`.
- UI parity
  - Network tab → confirm the POST body matches the working curl request.

---

## Open Questions (To Finalize Design)
- Scope: Which tables beyond `employees` must be first‑class (projects, assignments, invoices, timesheets)? Any mandatory join logic (e.g., current assignment per employee)?
- Query styles: primary use cases — point lookups ("max rate"), list filters ("all devs > $25/hr"), or cross‑table reasoning ("Who leads the highest‑rate project?")?
- Fields & normalization: consistent date fields, currencies, units? Do we need canonicalization and original fields?
- Synonyms: domain vocabulary to seed sparse retrieval (dev/engineer/contractor, dept abbreviations, project codes)?
- Freshness: how often do tables change? Prefer refresh schedule for a materialized view or on‑demand TVF computation?
- Guardrails: keep strict fallback for non‑cited answers, or allow partial answers with explicit "missing fields" notes?

---

## Next Steps
- Define the TVF/materialized view schema (columns above) and implement `embeddable_text` templates per entity type.
- Enable/verify payload indexes for the high‑value metadata fields.
- Run cross‑table queries without filters to validate hybrid recall; add filters per task where needed.
- Tune `STRICT_RAG_MIN_SCORE` after observing top_scores in `vector_search_done` events.

