-- Origem confirmada pelo responsável: America/Sao_Paulo, inclusive no histórico.
-- Executar como dono das tabelas, com ETL parado. Não usar offset fixo:
-- a zona IANA preserva as regras históricas de horário de verão.
BEGIN;
SET LOCAL lock_timeout = '5s';
LOCK TABLE etl_private.sensor_data, etl_private.buoy_data IN ACCESS EXCLUSIVE MODE;

DO $$
DECLARE
    table_name TEXT;
    column_type OID;
    invalid_time BOOLEAN;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['sensor_data', 'buoy_data'] LOOP
        SELECT atttypid INTO column_type
        FROM pg_catalog.pg_attribute
        WHERE attrelid = format('etl_private.%I', table_name)::regclass
          AND attname = 'timestamp' AND NOT attisdropped;

        IF column_type = 'timestamp without time zone'::regtype THEN
            -- Round-trip detecta gaps; +/- 1h detecta sobreposição nas transições
            -- de horário de verão de America/Sao_Paulo.
            EXECUTE format($check$
                SELECT EXISTS (
                    SELECT 1 FROM etl_private.%I
                    WHERE NOT isfinite(timestamp)
                       OR (timestamp AT TIME ZONE 'America/Sao_Paulo')
                          AT TIME ZONE 'America/Sao_Paulo' <> timestamp
                       OR ((timestamp AT TIME ZONE 'America/Sao_Paulo') + interval '1 hour')
                          AT TIME ZONE 'America/Sao_Paulo' = timestamp
                       OR ((timestamp AT TIME ZONE 'America/Sao_Paulo') - interval '1 hour')
                          AT TIME ZONE 'America/Sao_Paulo' = timestamp
                )
            $check$, table_name) INTO invalid_time;
            IF invalid_time THEN
                RAISE EXCEPTION 'Instantes não finitos, ambíguos ou inexistentes em %. Revisão manual necessária; nenhum instante foi escolhido automaticamente.', table_name;
            END IF;
            EXECUTE format(
                'ALTER TABLE etl_private.%I ALTER COLUMN timestamp TYPE TIMESTAMPTZ USING timestamp AT TIME ZONE ''America/Sao_Paulo''',
                table_name
            );
        ELSIF column_type IS DISTINCT FROM 'timestamp with time zone'::regtype THEN
            RAISE EXCEPTION 'Tipo de timestamp inesperado em %.', table_name;
        END IF;
    END LOOP;
END $$;
COMMIT;
