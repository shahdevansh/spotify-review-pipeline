-- Aggregate-only, versioned evaluation is independent of frozen run outputs.
-- RESTRICT deliberately prevents replacement of a run with published reports.
CREATE TABLE IF NOT EXISTS spotify_evaluation_reports (
    report_id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES spotify_runs(run_id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('pilot_audit', 'candidate_comparison')),
    schema_version text NOT NULL,
    label_config text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (payload ?& ARRAY['report_id','run_id','kind','schema_version','label_config']),
    CHECK (jsonb_typeof(payload->'report_id') = 'string'
       AND jsonb_typeof(payload->'run_id') = 'string'
       AND jsonb_typeof(payload->'kind') = 'string'
       AND jsonb_typeof(payload->'schema_version') = 'string'
       AND jsonb_typeof(payload->'label_config') = 'string'),
    CHECK (payload->>'report_id' = report_id),
    CHECK (payload->>'run_id' = run_id),
    CHECK (payload->>'kind' = kind),
    CHECK (payload->>'schema_version' = schema_version),
    CHECK (payload->>'label_config' = label_config)
);
CREATE INDEX IF NOT EXISTS spotify_evaluation_reports_run
    ON spotify_evaluation_reports(run_id, kind, created_at DESC, report_id);

CREATE OR REPLACE FUNCTION spotify_evaluation_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Evaluation reports are immutable; publish a new report_id';
END
$$;
DROP TRIGGER IF EXISTS spotify_evaluation_immutable ON spotify_evaluation_reports;
CREATE TRIGGER spotify_evaluation_immutable
    BEFORE UPDATE OR DELETE ON spotify_evaluation_reports
    FOR EACH ROW EXECUTE FUNCTION spotify_evaluation_immutable();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'spotify_dashboard_reader') THEN
        GRANT SELECT ON spotify_evaluation_reports TO spotify_dashboard_reader;
    END IF;
END
$$;
