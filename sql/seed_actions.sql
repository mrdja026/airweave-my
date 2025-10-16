-- Seed actions/decisions schema and semantic views for AI‑CEO demo
-- Creates writeable tables and embeddable summary views so actions/decisions
-- are searchable in Airweave just like events and summaries.

BEGIN;

-- 1) Performed actions — moves, assignments, emails
CREATE TABLE IF NOT EXISTS public.performed_actions (
  id               SERIAL PRIMARY KEY,
  action_type      TEXT NOT NULL CHECK (action_type IN ('assign','reassign','email')),
  actor_employee_id INT REFERENCES public.employees(id) ON DELETE SET NULL,
  from_project_id  INT REFERENCES public.projects(id) ON DELETE SET NULL,
  to_project_id    INT REFERENCES public.projects(id) ON DELETE SET NULL,
  task             TEXT,
  email_to         TEXT,
  email_subject    TEXT,
  email_body       TEXT,
  source_event_id  INT REFERENCES public.project_events(id) ON DELETE SET NULL,
  reason           TEXT,
  status           TEXT NOT NULL DEFAULT 'planned',  -- planned | in_progress | completed | sent
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2) CEO decisions — high‑level choices with rationale
CREATE TABLE IF NOT EXISTS public.ceo_decisions (
  id            SERIAL PRIMARY KEY,
  decision_text TEXT NOT NULL,
  rationale     TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3) Semantic view for actions — one summary row per action
CREATE OR REPLACE VIEW public.performed_actions_text AS
WITH evt AS (
  SELECT id AS event_id, event_type, requested_at
  FROM public.project_events
)
SELECT
  pa.id AS action_id,
  pa.action_type,
  e.name AS actor_employee_name,
  pf.name AS from_project_name,
  pt.name AS to_project_name,
  COALESCE(pt.name, pf.name) AS project_name,
  pa.task,
  pa.email_to,
  pa.email_subject,
  pa.status,
  pa.reason,
  pa.created_at,
  pa.source_event_id,
  evt.event_type   AS source_event_type,
  evt.requested_at AS source_event_requested_at,
  FORMAT(
    'Action %s: %s%s%s%s. Status: %s. Reason: %s%s.',
    pa.action_type,
    COALESCE('actor ' || e.name || ' ', ''),
    CASE
      WHEN pa.action_type='reassign' AND pf.name IS NOT NULL AND pt.name IS NOT NULL
        THEN FORMAT('moved from %s to %s', pf.name, pt.name)
      WHEN pa.action_type='assign' AND pt.name IS NOT NULL
        THEN FORMAT('assigned to %s', pt.name)
      WHEN pa.action_type='email' AND pa.email_to IS NOT NULL
        THEN FORMAT('email to %s', pa.email_to)
      ELSE ''
    END,
    CASE WHEN pa.task IS NOT NULL THEN FORMAT(' task: %s', pa.task) ELSE '' END,
    CASE WHEN pa.email_subject IS NOT NULL THEN FORMAT(' subject: %s', pa.email_subject) ELSE '' END,
    pa.status,
    COALESCE(pa.reason,'none'),
    CASE WHEN evt.event_type IS NOT NULL
      THEN FORMAT(' (source event: %s on %s)', evt.event_type, TO_CHAR(evt.requested_at,'YYYY-MM-DD'))
      ELSE ''
    END
  ) AS summary_text
FROM public.performed_actions pa
LEFT JOIN public.employees e ON e.id = pa.actor_employee_id
LEFT JOIN public.projects  pf ON pf.id = pa.from_project_id
LEFT JOIN public.projects  pt ON pt.id = pa.to_project_id
LEFT JOIN evt              ON evt.event_id = pa.source_event_id
ORDER BY pa.created_at DESC;

-- 4) Semantic view for CEO decisions — one summary row per decision
CREATE OR REPLACE VIEW public.ceo_decisions_text AS
SELECT
  d.id          AS decision_id,
  d.created_at,
  d.decision_text,
  d.rationale,
  FORMAT(
    'CEO decision on %s: %s. Rationale: %s.',
    TO_CHAR(d.created_at,'YYYY-MM-DD'),
    d.decision_text,
    COALESCE(d.rationale,'none')
  ) AS summary_text
FROM public.ceo_decisions d
ORDER BY d.created_at DESC;

COMMIT;

-- Quick checks (optional):
-- SELECT * FROM public.performed_actions_text LIMIT 5;
-- SELECT * FROM public.ceo_decisions_text LIMIT 5;

