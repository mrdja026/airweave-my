#!/usr/bin/env bash
set -euo pipefail

# EOD export helper: hits the Airweave API and saves Markdown to a file.
#
# Env defaults (override via env or flags):
#   API_URL=http://localhost:8001
#   COLLECTION=helloworld-e4fh2w
#   PROJECT=BigCompany
#   PROMPT_DATE=today            # or "Oct 16, 2025"
#   OUT=Demo/EOD_${PROJECT}_$(date +%F).md
#   RERANK=true
#   ROWS_ONLY=false              # if true, generate_answer=false and render rows
#
# Usage examples:
#   ./scripts/eod_export.sh
#   PROJECT=BigCompany PROMPT_DATE="Oct 16, 2025" ./scripts/eod_export.sh
#   ROWS_ONLY=true ./scripts/eod_export.sh
#   OUT=my_eod.md ./scripts/eod_export.sh

API_URL=${API_URL:-http://localhost:8001}
COLLECTION=${COLLECTION:-helloworld-e4fh2w}
PROJECT=${PROJECT:-BigCompany}
PROMPT_DATE=${PROMPT_DATE:-today}
RERANK=${RERANK:-true}
ROWS_ONLY=${ROWS_ONLY:-false}

OUT_DEFAULT="Demo/EOD_${PROJECT}_$(date +%F).md"
OUT=${OUT:-$OUT_DEFAULT}

mkdir -p "$(dirname "$OUT")"

body() {
  local generate_answer=$1
  cat <<JSON
{
  "query": "End-of-day summary for ${PROJECT} for ${PROMPT_DATE}: list today’s events (incident, new lead, sick leave), actions taken (moves, assignments, emails), and rationale. Then add a section titled \"Model Reasoning (concise)\" with 3–5 short bullets explaining key signals from the retrieved rows, stated as verifiable justifications (no hidden chain-of-thought). Include assumptions, tradeoffs, and a one-line confidence. End with [[1]].",
  "retrieval_strategy": "hybrid",
  "generate_answer": ${generate_answer},
  "expand_query": false,
  "interpret_filters": false,
  "rerank": ${RERANK},
  "filter": {"must": [{"key": "project_name", "match": {"value": "${PROJECT}"}}]}
}
JSON
}

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

if [[ "$ROWS_ONLY" == "true" ]]; then
  curl -s -X POST "${API_URL}/collections/${COLLECTION}/search" \
    -H 'Content-Type: application/json' \
    --data "$(body false)" > "$TMP"

  {
    echo "# EOD (Rows) — ${PROJECT} — ${PROMPT_DATE}"
    echo
    # Robust rendering even if .results is null or empty
    jq -r '
      def picktext: .payload.summary_text // .payload.md_content // .payload.embeddable_text // .payload.content // empty;
      if ((.results // []) | length) == 0 then
        "No results."
      else
        (.results // []) as $rows |
        ($rows | map(.payload.table_name) | unique // []) as $tables |
        ( $tables[] | select(. != null) ) as $t |
        "\n## " + $t + "\n",
        ( $rows
          | map(select(.payload.table_name == $t))
          | map("- " + (picktext))
          | .[] )
      end' "$TMP"
  } > "$OUT"
  echo "Saved rows to $OUT"
  exit 0
fi

# Completion mode
curl -s -X POST "${API_URL}/collections/${COLLECTION}/search" \
  -H 'Content-Type: application/json' \
  --data "$(body true)" > "$TMP"

COMPLETION=$(jq -r '.completion // .message // empty' "$TMP")
if [[ -z "$COMPLETION" || "$COMPLETION" == "null" ]]; then
  echo "No completion returned; falling back to rows." >&2
  ROWS_ONLY=true OUT="$OUT" API_URL="$API_URL" COLLECTION="$COLLECTION" PROJECT="$PROJECT" PROMPT_DATE="$PROMPT_DATE" \
    bash "$0"
  exit 0
fi

{
  echo "# EOD — ${PROJECT} — ${PROMPT_DATE}"
  echo
  printf "%s\n" "$COMPLETION"
} > "$OUT"

echo "Saved EOD to $OUT"
