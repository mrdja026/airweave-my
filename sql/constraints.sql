-- Constraints tables and semantic view
-- - Adds a lightweight work_plans table to capture planned hours per person/task/date
-- - Derives a constraints summary view for projects with schedule, capacity, and cost estimates

BEGIN;

-- Work plans: minimal structure for day-level planning
CREATE TABLE IF NOT EXISTS public.work_plans (
  id               SERIAL PRIMARY KEY,
  project_id       INT NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  employee_id      INT REFERENCES public.employees(id) ON DELETE SET NULL,
  task             TEXT NOT NULL,
  planned_hours    NUMERIC(6,2) NOT NULL CHECK (planned_hours >= 0),
  plan_date        DATE NOT NULL DEFAULT CURRENT_DATE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, employee_id, task, plan_date)
);

-- Constraints summary: schedule, capacity (availability), and cost estimate
CREATE OR REPLACE VIEW public.project_constraints_text AS
WITH
  p AS (
    SELECT id, name FROM public.projects
  ),
  due_items AS (
    SELECT e.project_id,
           COUNT(*) FILTER (WHERE e.deadline IS NOT NULL AND e.deadline >= CURRENT_DATE AND e.deadline <= CURRENT_DATE + INTERVAL '7 days') AS due_next_7,
           MIN(e.deadline) FILTER (WHERE e.deadline IS NOT NULL AND e.deadline >= CURRENT_DATE) AS next_deadline
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
  rates AS (
    SELECT pa.project_id, pa.employee_id, pa.hourly_rate
    FROM public.project_assignments pa
  ),
  plan_cost AS (
    SELECT wp.project_id,
           COALESCE(SUM(wp.planned_hours * r.hourly_rate), 0)::NUMERIC(12,2) AS planned_cost_today,
           COUNT(*) AS planned_items
    FROM public.work_plans wp
    LEFT JOIN rates r ON r.project_id = wp.project_id AND r.employee_id = wp.employee_id
    WHERE wp.plan_date = CURRENT_DATE
    GROUP BY wp.project_id
  )
SELECT
  proj.id AS project_id,
  proj.name AS project_name,
  (
    'Constraints for ' || proj.name || ' on ' || TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD') ||
    ' — Due next 7 days: ' || COALESCE(d.due_next_7::text, '0') ||
    ' (next: ' || COALESCE(TO_CHAR(d.next_deadline, 'YYYY-MM-DD'), 'n/a') || '). ' ||
    'Availability events today: ' || COALESCE(a.availability_events::text, '0') ||
    ' (' || COALESCE(a.availability_notes, 'none') || '). ' ||
    'Planned items: ' || COALESCE(pc.planned_items::text, '0') || ', planned cost today: ' ||
    TO_CHAR(COALESCE(pc.planned_cost_today, 0), 'FM999999990.00')
  ) AS summary_text
FROM p proj
LEFT JOIN due_items d ON d.project_id = proj.id
LEFT JOIN availability_today a ON a.project_id = proj.id
LEFT JOIN plan_cost pc ON pc.project_id = proj.id
ORDER BY proj.id;

COMMIT;

-- Checks:
-- SELECT * FROM public.project_constraints_text WHERE project_name='BigCompany';
