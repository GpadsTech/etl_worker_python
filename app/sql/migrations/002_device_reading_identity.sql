-- Executar com o ETL parado, backup disponível e ON_ERROR_STOP=1.
-- Destino: tabelas PostgreSQL comuns no schema public.
-- Tabelas particionadas ou com herança exigem transferência prévia para tabelas comuns.
-- Duplicidades são bloqueadas, nunca eliminadas automaticamente.
BEGIN;
SET LOCAL lock_timeout = '5s';

LOCK TABLE public.sensor_data, public.buoy_data IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_inherits
        WHERE inhparent IN ('public.sensor_data'::regclass, 'public.buoy_data'::regclass)
           OR inhrelid IN ('public.sensor_data'::regclass, 'public.buoy_data'::regclass)
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_class
        WHERE oid IN ('public.sensor_data'::regclass, 'public.buoy_data'::regclass)
          AND relkind <> 'r'
    ) THEN
        RAISE EXCEPTION 'A migração 002 exige tabelas comuns, sem particionamento ou herança. Transfira os dados antes de continuar.';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.sensor_data
        GROUP BY sensor_id, firebase_id HAVING count(*) > 1
    ) OR EXISTS (
        SELECT 1 FROM public.buoy_data
        GROUP BY buoy_id, firebase_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Existem leituras repetidas por equipamento/firebase_id. Revisão manual necessária; nenhum dado foi removido.';
    END IF;
END $$;

ALTER TABLE public.sensor_data DROP CONSTRAINT sensor_data_pkey;
ALTER TABLE public.sensor_data ADD CONSTRAINT sensor_data_pkey
    PRIMARY KEY (sensor_id, firebase_id);
ALTER TABLE public.buoy_data DROP CONSTRAINT buoy_data_pkey;
ALTER TABLE public.buoy_data ADD CONSTRAINT buoy_data_pkey
    PRIMARY KEY (buoy_id, firebase_id);

COMMIT;
