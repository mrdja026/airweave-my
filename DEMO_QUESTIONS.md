# Demo Questions Aligned to AI Solution Eng Brief

Use these with the UI (same collection `helloworld-e4fh2w`). For each question, apply the matching filter preset from `airweave/demo_filters/filters.txt` where noted.

## Observe (What changed?)
- What changed today for BigCompany? Summarize impact, risks, and next steps.  
  Filter: `events_open_bigcompany`
- List all open high‑priority events for BigCompany with deadlines and estimates.  
  Filter: `events_open_high_priority` (combine `events_open` + `events_high_priority` in the UI)
- Show recent change requests for BigCompany with current status and owner.  
  Filter: `change_requests_all` or `change_requests_open_bigcompany`
- Are there any availability issues affecting BigCompany’s project today?  
  Filter: `availability_issues`

## Plan (What should we do?)
- Given the latest change request for BigCompany, propose a one‑day plan with owners, due dates, scope, risks, and communication notes.  
  Filter: `change_requests_open_bigcompany`
- Considering current team composition and rates, propose a plan to deliver the change request within 40 hours, prioritizing lowest cost without risk to quality.  
  Filter: `team_summary_for_project_bigcompany` (optionally run a second pass with `employees_only`)
- If Grace or Frank becomes unavailable mid‑day, reassign tasks to keep the deadline, and justify the trade‑offs.  
  Filter: `team_summary_for_project_bigcompany`

## Act (Communications / tasks)
- Draft a status update to Client A explaining the plan for the change request, expected timeline, and any risks.  
  Filter: `change_requests_open_bigcompany`
- Create an internal task list for the engineering team with 3–5 bullet items and owners.  
  Filter: `change_requests_open_bigcompany`
- Draft a short email to Sales with the context of the last “New Lead” and recommended next step.  
  Filter: `new_leads`

## Log (What happened and why?)
- End‑of‑day summary: what requests were processed, what actions were taken, and why. Include any follow‑ups for tomorrow.  
  Filter: `events_for_project_bigcompany`
- Compare today’s change request to historical requests for BigCompany. What risks previously occurred and how were they mitigated?  
  Filter: `events_for_project_bigcompany`

## Point Lookups (quick checks)
- Which employee has the highest rate? Return the name and rate.  
  Filter: `employees_only`
- Summarize team and costs for project BigCompany.  
  Filter: `team_summary_for_project_bigcompany`

## Tips
- If you need “today” semantics, keep the filter scoped to `project_event_history_text` and include the word “today” in the natural‑language query. Date‑range operators vary by backend version.
- Keep retrieval `hybrid` and generation enabled for concise answers with citations.
