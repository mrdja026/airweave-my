-- Simulate one workday: Observe → Plan → Act → Log for BigCompany
-- Safe to re-run; actions/decisions and work plans are inserted idempotently via UNIQUE keys or NOT EXISTS guards.

BEGIN;

-- Ensure dependencies exist
INSERT INTO public.projects (name)
SELECT 'BigCompany' WHERE NOT EXISTS (SELECT 1 FROM public.projects WHERE name='BigCompany');

-- Shortcuts
WITH
  pid AS (SELECT id FROM public.projects WHERE name='BigCompany'),
  frank AS (SELECT id FROM public.employees WHERE name='Frank'),
  grace AS (SELECT id FROM public.employees WHERE name='Grace'),
  bob   AS (SELECT id FROM public.employees WHERE name='Bob')
SELECT 1;

-- OBSERVE: Collect today’s events for BigCompany
WITH today_events AS (
  SELECT e.*
  FROM public.project_events e
  JOIN public.projects p ON p.id = e.project_id
  WHERE p.name='BigCompany' AND DATE(e.requested_at AT TIME ZONE 'UTC') = CURRENT_DATE
)
SELECT COUNT(*) FROM today_events;  -- no-op for visibility

-- PLAN: Create or update a lightweight work plan for today (hours by role)
-- Requires public.work_plans (from constraints.sql)
WITH p AS (SELECT id AS project_id FROM public.projects WHERE name='BigCompany'),
     g AS (SELECT id AS employee_id FROM public.employees WHERE name='Grace'),
     b AS (SELECT id AS employee_id FROM public.employees WHERE name='Bob')
INSERT INTO public.work_plans (project_id, employee_id, task, planned_hours, plan_date)
SELECT project_id, employee_id, 'CSV export (backend)', 8.0, CURRENT_DATE FROM p JOIN g ON TRUE
ON CONFLICT (project_id, employee_id, task, plan_date) DO NOTHING;

WITH p AS (SELECT id AS project_id FROM public.projects WHERE name='BigCompany'),
     b AS (SELECT id AS employee_id FROM public.employees WHERE name='Bob')
INSERT INTO public.work_plans (project_id, employee_id, task, planned_hours, plan_date)
SELECT project_id, employee_id, 'CSV export (frontend button)', 4.0, CURRENT_DATE FROM p JOIN b ON TRUE
ON CONFLICT (project_id, employee_id, task, plan_date) DO NOTHING;

-- ACT: Insert performed actions (assignment, reassignment, client email)
-- Requires public.performed_actions (from seed_actions.sql)
WITH proj AS (SELECT id AS project_id FROM public.projects WHERE name='BigCompany'),
     ef   AS (SELECT id AS employee_id FROM public.employees WHERE name='Frank'),
     eg   AS (SELECT id AS employee_id FROM public.employees WHERE name='Grace'),
     csv  AS (
       SELECT e.id AS event_id
       FROM public.project_events e
       JOIN public.projects p ON p.id=e.project_id
       WHERE p.name='BigCompany'
         AND (e.event_type ILIKE 'Change Request:%CSV%' OR e.description ILIKE '%CSV export%')
       ORDER BY requested_at DESC
       LIMIT 1
     )
INSERT INTO public.performed_actions (action_type, actor_employee_id, to_project_id, task, source_event_id, reason, status)
SELECT 'assign', ef.employee_id, proj.project_id,
       'Implement Accounts CSV export with filters', csv.event_id,
       'Senior dev leads implementation', 'in_progress'
FROM proj, ef, csv
WHERE NOT EXISTS (
  SELECT 1 FROM public.performed_actions
  WHERE action_type='assign' AND task='Implement Accounts CSV export with filters'
    AND DATE(created_at) = CURRENT_DATE
);

WITH proj AS (SELECT id AS project_id FROM public.projects WHERE name='BigCompany'),
     eg   AS (SELECT id AS employee_id FROM public.employees WHERE name='Grace'),
     csv  AS (
       SELECT e.id AS event_id
       FROM public.project_events e
       JOIN public.projects p ON p.id=e.project_id
       WHERE p.name='BigCompany'
         AND (e.event_type ILIKE 'Change Request:%CSV%' OR e.description ILIKE '%CSV export%')
       ORDER BY requested_at DESC
       LIMIT 1
     )
INSERT INTO public.performed_actions (action_type, actor_employee_id, to_project_id, task, source_event_id, reason, status)
SELECT 'reassign', eg.employee_id, proj.project_id,
       'Move Grace to CSV export workstream', csv.event_id,
       'Cover urgent CSV export due 2025-10-20', 'completed'
FROM proj, eg, csv
WHERE NOT EXISTS (
  SELECT 1 FROM public.performed_actions
  WHERE action_type='reassign' AND task='Move Grace to CSV export workstream'
    AND DATE(created_at) = CURRENT_DATE
);

WITH proj AS (SELECT id AS project_id FROM public.projects WHERE name='BigCompany'),
     csv  AS (
       SELECT e.id AS event_id
       FROM public.project_events e
       JOIN public.projects p ON p.id=e.project_id
       WHERE p.name='BigCompany'
         AND (e.event_type ILIKE 'Change Request:%CSV%' OR e.description ILIKE '%CSV export%')
       ORDER BY requested_at DESC
       LIMIT 1
     )
INSERT INTO public.performed_actions (action_type, to_project_id, email_to, email_subject, email_body, source_event_id, reason, status)
SELECT 'email', proj.project_id,
       'client.a@example.com',
       'Status: Export Incident + CSV Delivery Plan',
       'Hi — We mitigated the export outage today and scheduled a one‑day build for the CSV export due Oct 20. Reassignments are in place to maintain timelines. Full post‑mortem in 24h. Best, CEO',
       csv.event_id,
       'Notify client of incident mitigation and CSV plan', 'sent'
FROM proj, csv
WHERE NOT EXISTS (
  SELECT 1 FROM public.performed_actions
  WHERE action_type='email' AND email_subject='Status: Export Incident + CSV Delivery Plan'
    AND DATE(created_at) = CURRENT_DATE
);

-- LOG: CEO decisions with rationale
INSERT INTO public.ceo_decisions (decision_text, rationale)
SELECT 'Prioritize export incident and keep CSV deadline 2025‑10‑20',
       'Incident affects production reporting; CSV deadline maintains client trust. Reassign to cover Alice’s absence.'
WHERE NOT EXISTS (
  SELECT 1 FROM public.ceo_decisions
  WHERE decision_text='Prioritize export incident and keep CSV deadline 2025‑10‑20'
    AND DATE(created_at) = CURRENT_DATE
);

INSERT INTO public.ceo_decisions (decision_text, rationale)
SELECT 'Proceed with one‑day CSV plan and add export observability',
       'Timebox work to 1 day; stream CSV; rate‑limit; add dashboards to catch regressions.'
WHERE NOT EXISTS (
  SELECT 1 FROM public.ceo_decisions
  WHERE decision_text='Proceed with one‑day CSV plan and add export observability'
    AND DATE(created_at) = CURRENT_DATE
);

COMMIT;

-- Quick checks:
-- SELECT * FROM public.performed_actions_text ORDER BY created_at DESC LIMIT 5;
-- SELECT * FROM public.ceo_decisions_text ORDER BY created_at DESC LIMIT 5;
-- SELECT * FROM public.work_plans WHERE plan_date = CURRENT_DATE;
