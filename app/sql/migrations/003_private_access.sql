-- Executar com o usuário de migração (dono das tabelas e com CREATEROLE).
-- Não cria logins, senhas ou associações de usuários aos grupos.
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['etl_writer', 'ai_reader'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
                role_name
            );
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_roles
            WHERE rolname = role_name
              AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
                   OR rolreplication OR rolbypassrls)
        ) OR EXISTS (
            SELECT 1 FROM pg_auth_members
            WHERE member = (SELECT oid FROM pg_roles WHERE rolname = role_name)
        ) OR EXISTS (
            SELECT 1 FROM pg_class
            WHERE relowner = (SELECT oid FROM pg_roles WHERE rolname = role_name)
        ) OR EXISTS (
            SELECT 1 FROM pg_namespace
            WHERE nspowner = (SELECT oid FROM pg_roles WHERE rolname = role_name)
        ) OR EXISTS (
            SELECT 1 FROM pg_database
            WHERE datdba = (SELECT oid FROM pg_roles WHERE rolname = role_name)
        ) THEN
            RAISE EXCEPTION 'Role % já existe com atributos ou heranças incompatíveis, ou é proprietária de objetos; revisão manual necessária.', role_name;
        END IF;
    END LOOP;
END $$;

CREATE SCHEMA IF NOT EXISTS etl_private;
REVOKE ALL ON SCHEMA etl_private FROM PUBLIC, etl_writer, ai_reader;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'sensor_data', 'buoy_data', 'etl_checkpoint', 'etl_rejections'
    ] LOOP
        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            IF to_regclass(format('etl_private.%I', table_name)) IS NOT NULL THEN
                RAISE EXCEPTION 'Tabela % existe em public e etl_private; revisão manual necessária.', table_name;
            END IF;
            EXECUTE format('ALTER TABLE public.%I SET SCHEMA etl_private', table_name);
        ELSIF to_regclass(format('etl_private.%I', table_name)) IS NULL THEN
            RAISE EXCEPTION 'Tabela % ausente; aplique as migrações 000/001/002 antes da 003.', table_name;
        END IF;
        EXECUTE format(
            'REVOKE ALL ON TABLE etl_private.%I FROM PUBLIC, etl_writer, ai_reader',
            table_name
        );
    END LOOP;
END $$;

-- Retira grants que podem ter sido herdados das tabelas no schema public do Supabase.
DO $$
DECLARE
    api_role TEXT;
    table_name TEXT;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA etl_private FROM %I', api_role);
            FOREACH table_name IN ARRAY ARRAY[
                'sensor_data', 'buoy_data', 'etl_checkpoint', 'etl_rejections'
            ] LOOP
                EXECUTE format(
                    'REVOKE ALL ON TABLE etl_private.%I FROM %I', table_name, api_role
                );
            END LOOP;
        END IF;
    END LOOP;
END $$;

GRANT USAGE ON SCHEMA etl_private TO etl_writer, ai_reader;
GRANT SELECT, INSERT ON etl_private.sensor_data, etl_private.buoy_data TO etl_writer;
GRANT SELECT, INSERT, UPDATE ON etl_private.etl_checkpoint, etl_private.etl_rejections
    TO etl_writer;
GRANT SELECT ON etl_private.sensor_data, etl_private.buoy_data TO ai_reader;

-- Sem permissões automáticas para futuras tabelas; conceder explicitamente
-- em cada nova migração. O usuário de migração permanece dono dos objetos.
ALTER DEFAULT PRIVILEGES IN SCHEMA etl_private REVOKE ALL ON TABLES FROM PUBLIC;
COMMIT;
