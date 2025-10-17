#!/usr/bin/env bash
set -euo pipefail

# UI Test Suite: runs Section 7 scenarios and writes Markdown files per scenario

# Config (override via env)
API_URL=${API_URL:-http://localhost:8001}
COLLECTION=${COLLECTION:-helloworld-e4fh2w}
PROJECT=${PROJECT:-BigCompany}
PROMPT_DATE=${PROMPT_DATE:-today}
OUTDIR=${OUTDIR:-Demo/UITests}

mkdir -p "$OUTDIR"

require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1'" >&2; exit 1; }; }
require curl; require jq

post() { # args: json_body
  curl -s -X POST "${API_URL}/collections/${COLLECTION}/search" \
    -H 'Content-Type: application/json' --data "$1"
}

write_md() { # args: outfile, title, json_response
  local out="$1"; shift
  local title="$1"; shift
  local tmp=$(mktemp)
  printf "%s" "$1" > "$tmp"

  {
    echo "# $title"
    echo
    local completion
    completion=$(jq -r '.completion // empty' "$tmp")
    if [[ -n "$completion" ]]; then
      printf "%s\n\n" "$completion"
    else
      echo "_No completion; showing retrieved rows._"; echo
    fi
    echo "## Sources"
    # Print up to 10 sources with table and summary
    jq -r '(
      .results // []
      | to_entries
      | .[0:10]
      | map( "- [" + ( (._index + 1|tostring) ) + "] " + (.value.payload.table_name // "") + " — " + ((.value.payload.summary_text // .value.payload.embeddable_text // "") | tostring | sub("\n";" ";"g") | .[0:200]) )
      | .[]
    )' "$tmp"
  } > "$out"
  rm -f "$tmp"
  echo "Saved: $out"
}

scenario() { # args: idx name json_body
  local idx="$1"; shift
  local name="$1"; shift
  local body="$1"; shift
  local file="$OUTDIR/$(printf "%02d" "$idx")_${name}.md"
  local resp
  resp=$(post "$body")
  write_md "$file" "$name — ${PROJECT} (${PROMPT_DATE})" "$resp"
}

# Common helpers
base_filter() { printf '{"must":[{"key":"project_name","match":{"value":"%s"}}]}' "$PROJECT"; }

# 1) EOD (broad reasoning) — filter {}
scenario 1 EOD_broad "$(jq -cn --arg q "End-of-day summary for ${PROJECT} for ${PROMPT_DATE}: list today’s events (incident, new lead, sick leave), actions taken (moves, assignments, emails), and rationale. Then add a section titled \"Model Reasoning (broad)\" with 8–12 evidence-based bullets, grouped across: Drivers, Constraints, Risks, Trade-offs, Alternatives, Dependencies, Assumptions, Unknowns, and Confidence. Each bullet should be a verifiable justification grounded in retrieved facts (no hidden chain-of-thought). End with [[1]]." '{query:$q,retrieval_strategy:"hybrid",generate_answer:true,expand_query:false,interpret_filters:false,rerank:true,filter:{}}')"

# 2) Deliverables — skipped per request

# 3) Constraints (disable temporal relevance) — filter {}
scenario 3 Constraints "$(jq -cn --arg q "Summarize constraints for ${PROJECT} today. End with [[1]]." '{query:$q,retrieval_strategy:"hybrid",generate_answer:true,expand_query:false,interpret_filters:false,temporal_relevance:0.0,rerank:true,filter:{}}')"

# 4) Actions — skipped per request

# 5) Decisions (direct) — filter {}
scenario 5 Decisions "$(jq -cn --arg q "List CEO decisions on ${PROMPT_DATE}. Return decision and rationale. End with [[1]]." '{query:$q,retrieval_strategy:"hybrid",generate_answer:true,expand_query:false,interpret_filters:false,rerank:true,filter:{}}')"

# 6) Incident Deep‑Dive — filter {}
scenario 6 Incident_Deep_Dive "$(jq -cn --arg q "Summarize today’s production incident for ${PROJECT}: impact, status, mitigations, and next steps. End with [[1]]." '{query:$q,retrieval_strategy:"hybrid",generate_answer:true,expand_query:false,interpret_filters:false,rerank:true,filter:{}}')"

# 7) New Lead — filter {}
scenario 7 New_Lead "$(jq -cn --arg q "A new lead asked for a proposal within 48 hours. Draft a short plan with owners, discovery questions, and a proposal outline. End with [[1]]." '{query:$q,retrieval_strategy:"hybrid",generate_answer:true,expand_query:false,interpret_filters:false,rerank:true,filter:{}}')"

# 8) Availability — filter {}
scenario 8 Availability "$(jq -cn --arg q "One engineer is out sick today. Recommend task reassignments to keep deadlines on track and note risks. End with [[1]]." '{query:$q,retrieval_strategy:"hybrid",generate_answer:true,expand_query:false,interpret_filters:false,rerank:true,filter:{}}')"

# 9) CSV export one‑day plan — filter {}
scenario 9 CSV_OneDay_Plan "$(jq -cn --arg q "One‑day plan to deliver Accounts CSV export with filter parity by 2025-10-20. Include owners (BE/FE/QA/SRE/PM), milestones, acceptance, and risks. End with [[1]]." '{query:$q,retrieval_strategy:"hybrid",generate_answer:true,expand_query:false,interpret_filters:false,rerank:true,filter:{}}')"

# 10) Client email — filter {}
scenario 10 Client_Email "$(jq -cn --arg q "Draft a client email for ${PROJECT} summarizing the export incident mitigation and the CSV export plan due Oct 20. Keep it professional and concise. End with [[1]]." '{query:$q,retrieval_strategy:"hybrid",generate_answer:true,expand_query:false,interpret_filters:false,rerank:true,filter:{}}')"

echo "\nAll scenario reports saved under: $OUTDIR"
