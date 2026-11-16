CREATE TABLE IF NOT EXISTS sensor_data (

    firebase_id TEXT NOT NULL,

    sensor_id TEXT NOT NULL,

    timestamp TIMESTAMP NOT NULL,

    ar DOUBLE PRECISION,
    chuva DOUBLE PRECISION,
    gas DOUBLE PRECISION,
    luz DOUBLE PRECISION,
    pressao DOUBLE PRECISION,
    rpm DOUBLE PRECISION,
    temperatura DOUBLE PRECISION,
    umidade DOUBLE PRECISION,
    vento DOUBLE PRECISION,
    volt DOUBLE PRECISION,

    PRIMARY KEY (firebase_id, timestamp)

);

CREATE TABLE IF NOT EXISTS buoy_data (

    firebase_id TEXT NOT NULL,

    buoy_id TEXT NOT NULL,

    timestamp TIMESTAMP NOT NULL,

    adc DOUBLE PRECISION,
    ph DOUBLE PRECISION,
    sensor_uv_v DOUBLE PRECISION,
    tensao_v DOUBLE PRECISION,
    turbidez_v DOUBLE PRECISION,

    PRIMARY KEY (firebase_id, timestamp)

);

SELECT create_hypertable(
    'sensor_data',
    'timestamp',
    if_not_exists => TRUE
);

SELECT create_hypertable(
    'buoy_data',
    'timestamp',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_sensor_timestamp
ON sensor_data(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_sensor_id
ON sensor_data(sensor_id);

CREATE INDEX IF NOT EXISTS idx_sensor_sensor_time
ON sensor_data(sensor_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_buoy_timestamp
ON buoy_data(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_buoy_id
ON buoy_data(buoy_id);

CREATE INDEX IF NOT EXISTS idx_buoy_time
ON buoy_data(buoy_id, timestamp DESC);

-- Checkpoint de leitura incremental por equipamento.
-- Guarda a última chave com medição ou rejeição já commitada.
CREATE TABLE IF NOT EXISTS etl_checkpoint (

    source TEXT NOT NULL,

    device_id TEXT NOT NULL,

    last_key TEXT NOT NULL,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (source, device_id)

);

-- Manter alinhado com migrations/001_etl_rejections.sql.
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
