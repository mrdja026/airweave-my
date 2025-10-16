-- Seed data and semantic view for Airweave demo
-- Creates minimal tables, inserts sample rows, and defines a view that
-- emits a single embeddable summary per project matching the example:
--   Project BigCompany has 4 devs (Frank, Grace, Alice, Bob), costing 97.00.
--   It has 0 non-devs (none), costing 0. Total staff 4, cost 97.00.
--   Leads: none (count 0).

BEGIN;

-- Drop old demo objects if re-running locally
DROP VIEW IF EXISTS public.project_team_summary_text CASCADE;
DROP TABLE IF EXISTS public.project_assignments CASCADE;
DROP TABLE IF EXISTS public.employees CASCADE;
DROP TABLE IF EXISTS public.projects CASCADE;

-- Projects
CREATE TABLE public.projects (
  id   SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

-- Employees (kept simple for demo)
CREATE TABLE public.employees (
  id    SERIAL PRIMARY KEY,
  name  TEXT NOT NULL UNIQUE
);

-- Project assignments with role and hourly rate captured at assignment time
CREATE TABLE public.project_assignments (
  project_id  INT NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  employee_id INT NOT NULL REFERENCES public.employees(id) ON DELETE CASCADE,
  role        TEXT NOT NULL,         -- e.g., Developer, Engineer, QA, PM
  is_lead     BOOLEAN NOT NULL DEFAULT FALSE,
  hourly_rate NUMERIC(10,2) NOT NULL,
  PRIMARY KEY (project_id, employee_id)
);

-- Seed: BigCompany project
INSERT INTO public.projects (name) VALUES ('BigCompany');

-- Seed: employees
INSERT INTO public.employees (name) VALUES
  ('Frank'),
  ('Grace'),
  ('Alice'),
  ('Bob');

-- Helper to resolve IDs
WITH ids AS (
  SELECT p.id AS pid,
         (SELECT id FROM public.employees WHERE name='Frank') AS frank,
         (SELECT id FROM public.employees WHERE name='Grace') AS grace,
         (SELECT id FROM public.employees WHERE name='Alice') AS alice,
         (SELECT id FROM public.employees WHERE name='Bob')   AS bob
  FROM public.projects p WHERE p.name='BigCompany'
)
INSERT INTO public.project_assignments (project_id, employee_id, role, is_lead, hourly_rate)
SELECT pid, frank, 'Developer', FALSE, 30.00 FROM ids UNION ALL
SELECT pid, grace, 'Developer', FALSE, 27.00 FROM ids UNION ALL
SELECT pid, alice, 'Developer', FALSE, 20.00 FROM ids UNION ALL
SELECT pid, bob,   'Developer', FALSE, 20.00 FROM ids;

-- Classifier: what counts as a "dev" role for this demo
-- Adjust list as needed (case-insensitive match)
CREATE OR REPLACE FUNCTION public._is_dev_role(role_text TEXT)
RETURNS BOOLEAN LANGUAGE SQL IMMUTABLE AS $$
  SELECT LOWER(TRIM($1)) IN ('dev','developer','engineer','software engineer','frontend','backend','fullstack');
$$;

-- Semantic summary view
CREATE VIEW public.project_team_summary_text AS
WITH base AS (
  SELECT pa.project_id,
         p.name AS project_name,
         e.name AS employee_name,
         pa.role,
         pa.is_lead,
         pa.hourly_rate,
         public._is_dev_role(pa.role) AS is_dev
  FROM public.project_assignments pa
  JOIN public.projects p   ON p.id = pa.project_id
  JOIN public.employees e  ON e.id = pa.employee_id
), agg AS (
  SELECT
    project_id,
    project_name,
    -- Dev stats
    COUNT(*) FILTER (WHERE is_dev)                AS dev_count,
    COALESCE(STRING_AGG(employee_name FILTER (WHERE is_dev) ORDER BY employee_name, ', '), 'none') AS dev_names,
    COALESCE(SUM(hourly_rate) FILTER (WHERE is_dev), 0)::NUMERIC(10,2) AS dev_cost,
    -- Non-dev stats
    COUNT(*) FILTER (WHERE NOT is_dev)            AS nondev_count,
    COALESCE(STRING_AGG(employee_name FILTER (WHERE NOT is_dev) ORDER BY employee_name, ', '), 'none') AS nondev_names,
    COALESCE(SUM(hourly_rate) FILTER (WHERE NOT is_dev), 0)::NUMERIC(10,2) AS nondev_cost,
    -- Lead stats
    COUNT(*) FILTER (WHERE is_lead)               AS lead_count,
    COALESCE(STRING_AGG(employee_name FILTER (WHERE is_lead) ORDER BY employee_name, ', '), 'none') AS lead_names,
    -- Totals
    COUNT(*)                                      AS total_count,
    COALESCE(SUM(hourly_rate), 0)::NUMERIC(10,2)  AS total_cost
  FROM base
  GROUP BY project_id, project_name
)
SELECT
  project_id,
  project_name,
  FORMAT(
    'Project %s has %s devs (%s), costing %.2f. It has %s non-devs (%s), costing %.0f. Total staff %s, cost %.2f. Leads: %s (count %s).',
    project_name,
    dev_count,
    dev_names,
    dev_cost,
    nondev_count,
    nondev_names,
    nondev_cost,
    total_count,
    total_cost,
    lead_names,
    lead_count
  ) AS summary_text
FROM agg
ORDER BY project_id;

COMMIT;

-- Quick check:
-- SELECT * FROM public.project_team_summary_text;
-- Expect row like:
--  project_id | project_name | summary_text
--  1          | BigCompany   | Project BigCompany has 4 devs (Frank, Grace, Alice, Bob), costing 97.00. It has 0 non-devs (none), costing 0. Total staff 4, cost 97.00. Leads: none (count 0).

