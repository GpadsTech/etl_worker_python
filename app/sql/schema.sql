-- Entrada psql: todas as definições estão nas migrações versionadas.
-- \ir resolve caminhos relativos a este arquivo, não ao diretório do terminal.
\set ON_ERROR_STOP on
-- Após a mudança de schema, não recriar as tabelas antigas em public.
SELECT to_regclass('etl_private.sensor_data') IS NOT NULL AS private_schema_ready \gset
\if :private_schema_ready
\else
\ir migrations/000_initial_schema.sql
\ir migrations/001_etl_rejections.sql
\ir migrations/002_device_reading_identity.sql
\endif
\ir migrations/003_private_access.sql
\ir migrations/004_measurement_timestamptz.sql
