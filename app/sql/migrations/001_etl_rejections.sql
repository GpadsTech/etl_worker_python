-- Aplicar antes de iniciar a versão do worker que persiste rejeições.
-- Não requer TimescaleDB: rejeições são uma tabela PostgreSQL comum.
CREATE TABLE IF NOT EXISTS etl_rejections (
    source TEXT NOT NULL CHECK (source IN ('sensores', 'boias')),
    device_id TEXT NOT NULL,
    firebase_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    reason TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    PRIMARY KEY (source, device_id, firebase_id)
);

CREATE INDEX IF NOT EXISTS idx_etl_rejections_pending
ON etl_rejections(last_attempt_at, source, device_id, firebase_id)
WHERE resolved_at IS NULL;
