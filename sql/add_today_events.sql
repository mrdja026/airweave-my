-- Adds three events for today for BigCompany to support EOD demo
-- - Incident: critical bug (production outage)
-- - New Lead
-- - Availability (sick leave)
-- Safe to re-run; uses NOW() for requested_at

BEGIN;

-- Ensure BigCompany exists (no-op if already present)
INSERT INTO public.projects (name)
SELECT 'BigCompany'
WHERE NOT EXISTS (SELECT 1 FROM public.projects WHERE name='BigCompany');

-- Critical bug (incident) today
WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, deadline, estimate_hours, status)
SELECT id, 'Client A', 'Incident: critical bug', 'High', NOW(), 'SRE',
       'Production outage due to critical bug in exports path', NOW() + INTERVAL '1 day', 12, 'Open'
FROM pid;

-- New lead today
WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, estimate_hours, status)
SELECT id, 'Client D', 'New Lead', 'Low', NOW(), 'Sales',
       'Inbound lead requesting a proposal for data sync integration within 48 hours', 8, 'Open'
FROM pid;

-- Alice called in sick (availability) today
WITH pid AS (SELECT id FROM public.projects WHERE name='BigCompany')
INSERT INTO public.project_events
  (project_id, client_name, event_type, priority, requested_at, requested_by, description, status)
SELECT id, 'Client A', 'Availability', 'Medium', NOW(), 'HR',
       'Alice called in sick today; reassign critical tasks to maintain deadlines', 'Open'
FROM pid;

COMMIT;

-- After running, refresh the Postgres source connection in Airweave.
-- Example:
--   curl -sS -X POST "http://localhost:8001/source-connections/CONS_SOURCE_ID/run"
