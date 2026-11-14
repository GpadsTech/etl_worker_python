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
-- Guarda a última chave do Firebase já processada (commitada).
CREATE TABLE IF NOT EXISTS etl_checkpoint (

    source TEXT NOT NULL,

    device_id TEXT NOT NULL,

    last_key TEXT NOT NULL,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (source, device_id)

);