-- Deliverables view: unified EOD evidence across events, actions, and decisions

BEGIN;

CREATE OR REPLACE VIEW public.eod_deliverables_text AS
SELECT 'event'::text AS section,
       e.project_id,
       p.name AS project_name,
       e.requested_at AS ts,
       e.summary_text
FROM public.project_event_history_text e
JOIN public.projects p ON p.id = e.project_id

UNION ALL

SELECT 'action'::text AS section,
       NULL::INT AS project_id,
       a.project_name,
       a.created_at AS ts,
       a.summary_text
FROM public.performed_actions_text a

UNION ALL

SELECT 'decision'::text AS section,
       NULL::INT AS project_id,
       pr.name AS project_name,
       d.created_at AS ts,
       d.summary_text
FROM public.ceo_decisions_text d
LEFT JOIN public.projects pr ON pr.name = 'BigCompany';

COMMIT;

-- Usage:
--  SELECT * FROM public.eod_deliverables_text WHERE project_name='BigCompany' ORDER BY ts DESC;
