-- Patch: constraints view without format() and without optional tables
-- Safe for DBs that do NOT have public.project_assignments. Hours-only summary.

BEGIN;

CREATE OR REPLACE VIEW public.project_constraints_text AS
WITH due_items AS (
  SELECT e.project_id,
         COUNT(*) FILTER (
           WHERE e.deadline IS NOT NULL
             AND e.deadline >= CURRENT_DATE
             AND e.deadline <= CURRENT_DATE + INTERVAL '7 days'
         ) AS due_next_7,
         MIN(e.deadline) FILTER (
           WHERE e.deadline IS NOT NULL AND e.deadline >= CURRENT_DATE
         ) AS next_deadline
  FROM public.project_events e
  GROUP BY e.project_id
),
availability_today AS (
  SELECT e.project_id,
         COUNT(*) FILTER (WHERE e.event_type ILIKE 'Availability%') AS availability_events,
         STRING_AGG(e.description, '; ') FILTER (WHERE e.event_type ILIKE 'Availability%') AS availability_notes
  FROM public.project_events e
  WHERE DATE(e.requested_at AT TIME ZONE 'UTC') = CURRENT_DATE
  GROUP BY e.project_id
),
plan_hours AS (
  SELECT wp.project_id,
         COUNT(*) AS planned_items,
         COALESCE(SUM(wp.planned_hours), 0)::NUMERIC(12,2) AS planned_hours_today
  FROM public.work_plans wp
  WHERE wp.plan_date = CURRENT_DATE
  GROUP BY wp.project_id
)
SELECT
  p.id   AS project_id,
  p.name AS project_name,
  (
    'Constraints for ' || p.name ||
    ' on ' || TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD') ||
    ' — Due next 7 days: ' || COALESCE(d.due_next_7::text, '0') ||
    ' (next: ' || COALESCE(TO_CHAR(d.next_deadline, 'YYYY-MM-DD'), 'n/a') || '). ' ||
    'Availability events today: ' || COALESCE(a.availability_events::text, '0') ||
    ' (' || COALESCE(a.availability_notes, 'none') || '). ' ||
    'Planned items: ' || COALESCE(ph.planned_items::text, '0') || ', planned hours today: ' ||
    TO_CHAR(COALESCE(ph.planned_hours_today, 0), 'FM999999990.00')
  ) AS summary_text
FROM public.projects p
LEFT JOIN due_items          d  ON d.project_id  = p.id
LEFT JOIN availability_today a  ON a.project_id  = p.id
LEFT JOIN plan_hours         ph ON ph.project_id = p.id
ORDER BY p.id;

COMMIT;

