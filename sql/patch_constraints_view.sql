-- Patch: redefine project_constraints_text to avoid FORMAT printf specifiers
-- Works whether project_assignments exists or not; uses cost if available, otherwise hours.

BEGIN;

DO $$
BEGIN
  IF to_regclass('public.project_assignments') IS NOT NULL THEN
    -- Cost-aware version (project_assignments exists)
    EXECUTE $v$
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
      plan_cost AS (
        SELECT wp.project_id,
               COUNT(*) AS planned_items,
               COALESCE(SUM(wp.planned_hours * pa.hourly_rate), 0)::NUMERIC(12,2) AS planned_cost_today
        FROM public.work_plans wp
        LEFT JOIN public.project_assignments pa
          ON pa.project_id = wp.project_id AND pa.employee_id = wp.employee_id
        WHERE wp.plan_date = CURRENT_DATE
        GROUP BY wp.project_id
      )
      SELECT p.id AS project_id,
             p.name AS project_name,
             FORMAT(
               'Constraints for %s on %s — Due next 7 days: %s (next: %s). Availability events today: %s (%s). Planned items: %s, planned cost today: %s.',
               p.name,
               TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD'),
               COALESCE(d.due_next_7::text, '0'),
               COALESCE(TO_CHAR(d.next_deadline, 'YYYY-MM-DD'), 'n/a'),
               COALESCE(a.availability_events::text, '0'),
               COALESCE(a.availability_notes, 'none'),
               COALESCE(pc.planned_items::text, '0'),
               TO_CHAR(COALESCE(pc.planned_cost_today, 0), 'FM999999990.00')
             ) AS summary_text
      FROM public.projects p
      LEFT JOIN due_items d ON d.project_id = p.id
      LEFT JOIN availability_today a ON a.project_id = p.id
      LEFT JOIN plan_cost pc ON pc.project_id = p.id
      ORDER BY p.id;
    $v$;
  ELSE
    -- Hours-only version (no project_assignments)
    EXECUTE $v$
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
      SELECT p.id AS project_id,
             p.name AS project_name,
             FORMAT(
               'Constraints for %s on %s — Due next 7 days: %s (next: %s). Availability events today: %s (%s). Planned items: %s, planned hours today: %s.',
               p.name,
               TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD'),
               COALESCE(d.due_next_7::text, '0'),
               COALESCE(TO_CHAR(d.next_deadline, 'YYYY-MM-DD'), 'n/a'),
               COALESCE(a.availability_events::text, '0'),
               COALESCE(a.availability_notes, 'none'),
               COALESCE(ph.planned_items::text, '0'),
               TO_CHAR(COALESCE(ph.planned_hours_today, 0), 'FM999999990.00')
             ) AS summary_text
      FROM public.projects p
      LEFT JOIN due_items d ON d.project_id = p.id
      LEFT JOIN availability_today a ON a.project_id = p.id
      LEFT JOIN plan_hours ph ON ph.project_id = p.id
      ORDER BY p.id;
    $v$;
  END IF;
END $$;

COMMIT;
