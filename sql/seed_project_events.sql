-- Seed project events and a semantic view for Airweave demo
-- Adds a minimal events table, creates an embeddable summary view, and
-- seeds a small history for the 'BigCompany' project including a new
-- change request for today. Safe to re-run.

BEGIN;

-- 1) Minimal events table (kept generic for demo)
CREATE TABLE IF NOT EXISTS public.project_events (
  id             SERIAL PRIMARY KEY,
  project_id     INT NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  client_name    TEXT NOT NULL,
  event_type     TEXT NOT NULL,      -- e.g., Change Request, Acceleration, New Lead, Availability
  priority       TEXT NOT NULL,      -- e.g., High, Medium, Low
  requested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  requested_by   TEXT,
  description    TEXT,
  deadline       DATE,
  estimate_hours INT,
  status         TEXT NOT NULL DEFAULT 'Open',  -- Open, Closed, In Progress
  outcome        TEXT
);

-- 2) Ensure BigCompany exists (no-op if already present)
INSERT INTO public.projects (name)
SELECT 'BigCompany'
WHERE NOT EXISTS (SELECT 1 FROM public.projects WHERE name='BigCompany');

-- 3) Semantic view: one row per event with a readable, embeddable summary
CREATE OR REPLACE VIEW public.project_event_history_text AS
SELECT
  e.id               AS event_id,
  e.project_id,
  p.name             AS project_name,
  e.client_name,
  e.event_type,
  e.priority,
  e.requested_at,
  e.deadline,
  e.estimate_hours,
  e.status,
  e.outcome,
  FORMAT(
    'On %s, client %s requested %s for project %s (priority %s, deadline %s, estimate %s h). Status: %s. Notes: %s.',
    TO_CHAR(e.requested_at,'YYYY-MM-DD'),
    e.client_name,
    e.event_type,
    p.name,
    e.priority,
    COALESCE(TO_CHAR(e.deadline,'YYYY-MM-DD'),'n/a'),
    COALESCE(e.estimate_hours::text,'n/a'),
    e.status,
    COALESCE(NULLIF(e.description,''),'none')
  ) AS summary_text
FROM public.project_events e
JOIN public.projects p ON p.id = e.project_id
ORDER BY e.requested_at DESC;

-- 4) Seed sample history for BigCompany
WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, deadline, estimate_hours, status, outcome)
SELECT id, 'Client A', 'Acceleration', 'High', '2025-09-01'::timestamptz, 'PM Team',
       'Accelerate delivery by one week due to exec demo', '2025-09-08', 32, 'Closed',
       'Scope trimmed; weekend work approved; delivered on time'
FROM pid
ON CONFLICT DO NOTHING;

WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, deadline, estimate_hours, status, outcome)
SELECT id, 'Client A', 'Availability', 'Medium', '2025-10-10'::timestamptz, 'HR',
       'Engineer out sick for two days; reassigned tasks to Grace', NULL, NULL, 'Closed',
       'Schedule adjusted; no slip'
FROM pid
ON CONFLICT DO NOTHING;

WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, deadline, estimate_hours, status, outcome)
SELECT id, 'Client B', 'New Lead', 'Low', '2025-09-15'::timestamptz, 'Sales',
       'Inbound lead for maintenance retainer; captured requirements', NULL, NULL, 'Closed',
       'Qualified as warm lead; pending proposal'
FROM pid
ON CONFLICT DO NOTHING;

-- Today (run date) change request; NOW() makes this dynamic
WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, deadline, estimate_hours, status, outcome)
SELECT id, 'Client A', 'Change Request: dashboard CSV export', 'High', NOW(), 'Jane Doe',
       'Add CSV export with filters for Accounts page', '2025-10-20', 40, 'Open',
       NULL
FROM pid
ON CONFLICT DO NOTHING;

-- Additional historical context (for richer guidance)
WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, deadline, estimate_hours, status, outcome)
SELECT id, 'Client A', 'Change Request: mobile parity', 'Low', '2025-08-05'::timestamptz, 'Product',
       'Add mobile‑parity features for reporting views', '2025-08-31', 60, 'Closed',
       'Rejected due to budget constraints; revisit in Q4'
FROM pid
ON CONFLICT DO NOTHING;

WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, deadline, estimate_hours, status, outcome)
SELECT id, 'Client A', 'SLA Risk', 'High', '2025-07-22'::timestamptz, 'SRE',
       'Traffic spikes risk SLA breach; add caching and rate limits', '2025-07-25', 16, 'Closed',
       'Added CDN caching + rate limits; no breach observed'
FROM pid
ON CONFLICT DO NOTHING;

WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, deadline, estimate_hours, status, outcome)
SELECT id, 'Client C', 'Change Request: integrate SSO', 'Medium', '2025-06-30'::timestamptz, 'IT',
       'Implement SAML SSO with Okta', '2025-07-15', 40, 'Closed',
       'Okta SAML integrated; phased rollout completed'
FROM pid
ON CONFLICT DO NOTHING;

COMMIT;

-- Quick checks (optional):
-- SELECT * FROM public.project_event_history_text ORDER BY requested_at DESC LIMIT 5;
-- SELECT project_name, event_type, priority, status, requested_at FROM public.project_event_history_text;
