-- Auditoria administrativa: nenhuma permissão adicional para o runtime.
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE TABLE IF NOT EXISTS etl_private.etl_corrections (
    correction_id UUID PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('sensores', 'boias')),
    device_id TEXT NOT NULL,
    firebase_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    actor TEXT NOT NULL DEFAULT session_user,
    corrected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    before_row JSONB NOT NULL,
    after_row JSONB NOT NULL
);
REVOKE ALL ON etl_private.etl_corrections FROM PUBLIC, etl_writer, ai_reader;
DO $$
DECLARE api_role TEXT;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('REVOKE ALL ON etl_private.etl_corrections FROM %I', api_role);
        END IF;
    END LOOP;
END $$;
COMMIT;
