"""Configuração de conexão sem acessar serviços ou registrar credenciais."""

import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from dotenv import dotenv_values

from app.config.config import Config, PROJECT_ROOT, load_environment
from app.database.connection import DatabaseConnection


class TestDatabaseConfig(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5433",
            "POSTGRES_DB": "test_db",
            "POSTGRES_USER": "test_user",
            "POSTGRES_PASSWORD": "test_password",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_local_defaults_preserve_connection_and_disable_tls(self):
        parameters = Config().database_parameters()
        self.assertEqual(parameters, {
            "host": "localhost", "port": 5433, "dbname": "test_db",
            "user": "test_user", "password": "test_password",
            "sslmode": "disable", "connect_timeout": 10,
            "options": "-c statement_timeout=60000 -c lock_timeout=5000 -c search_path=etl_private,pg_catalog",
        })

    def test_remote_defaults_verify_hostname_and_certificate(self):
        os.environ["POSTGRES_HOST"] = "example.pooler.supabase.com"
        self.assertEqual(Config().database_parameters()["sslmode"], "verify-full")

    def test_explicit_tls_certificate_and_timeouts_are_forwarded(self):
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "ca.crt"
            cert.write_text("certificate-placeholder")
            os.environ.update({
                "POSTGRES_SSLMODE": "verify-full",
                "POSTGRES_SSLROOTCERT": str(cert),
                "POSTGRES_CONNECT_TIMEOUT": "20",
                "POSTGRES_STATEMENT_TIMEOUT_MS": "120000",
                "POSTGRES_LOCK_TIMEOUT_MS": "2000",
            })
            parameters = Config().database_parameters()
            self.assertEqual(parameters["sslrootcert"], str(cert))
            self.assertEqual(parameters["sslmode"], "verify-full")
            self.assertEqual(parameters["connect_timeout"], 20)
            self.assertEqual(
                parameters["options"], "-c statement_timeout=120000 -c lock_timeout=2000 -c search_path=etl_private,pg_catalog",
            )

    def test_zero_disables_sql_timeouts(self):
        os.environ.update({
            "POSTGRES_STATEMENT_TIMEOUT_MS": "0", "POSTGRES_LOCK_TIMEOUT_MS": "0",
        })
        self.assertEqual(
            Config().database_parameters()["options"],
            "-c statement_timeout=0 -c lock_timeout=0 -c search_path=etl_private,pg_catalog",
        )

    def test_schema_override_and_invalid_schema(self):
        os.environ["POSTGRES_SCHEMA"] = "public"
        self.assertIn("-c search_path=public,pg_catalog", Config().database_parameters()["options"])
        for value in ("", "private,public", "bad -c superuser=on", "UPPER", "a" * 64):
            with self.subTest(schema=value):
                os.environ["POSTGRES_SCHEMA"] = value
                with self.assertRaisesRegex(ValueError, "POSTGRES_SCHEMA"):
                    Config().database_parameters()

    def test_invalid_integer_settings_do_not_echo_values(self):
        for name, invalid in (
            ("POSTGRES_PORT", "0"), ("POSTGRES_PORT", "65536"),
            ("POSTGRES_CONNECT_TIMEOUT", "0"),
            ("POSTGRES_STATEMENT_TIMEOUT_MS", "-1"),
            ("POSTGRES_LOCK_TIMEOUT_MS", "2147483648"),
            ("POSTGRES_CONNECT_TIMEOUT", "secret-invalid-value"),
        ):
            with self.subTest(setting=name, value=invalid):
                with patch.dict(os.environ, {name: invalid}):
                    with self.assertRaises(ValueError) as raised:
                        Config()
                    self.assertIn(name, str(raised.exception))
                    self.assertNotIn("secret-invalid-value", str(raised.exception))

    def test_missing_connection_fields_fail_before_driver(self):
        for name in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
            with self.subTest(setting=name):
                with patch.dict(os.environ, {name: ""}):
                    with self.assertRaisesRegex(ValueError, name):
                        Config().database_parameters()

    def test_invalid_tls_mode_is_rejected_without_echoing_value(self):
        os.environ["POSTGRES_SSLMODE"] = "secret-invalid-value"
        with self.assertRaisesRegex(ValueError, "^POSTGRES_SSLMODE inválido"):
            Config().database_parameters()

    def test_missing_certificate_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ["POSTGRES_SSLROOTCERT"] = str(Path(directory) / "missing.crt")
            with self.assertRaisesRegex(ValueError, "POSTGRES_SSLROOTCERT"):
                Config().database_parameters()

    def test_connection_passes_parameters_and_reuses_session(self):
        config = Config()
        connection = MagicMock()
        connection.closed = False
        connection.autocommit = False
        with patch("app.database.connection.config", config):
            with patch("app.database.connection.psycopg2.connect", return_value=connection) as connect:
                database = DatabaseConnection()
                self.assertIs(database.connect(), connection)
                self.assertIs(database.connect(), connection)
                connect.assert_called_once_with(**config.database_parameters())
                cursor = connection.cursor.return_value.__enter__.return_value
                cursor.execute.assert_called_once_with(
                    "SELECT set_config('statement_timeout', %s, false), "
                    "set_config('lock_timeout', %s, false), "
                    "set_config('search_path', %s, false)",
                    ("60000", "5000", "etl_private,pg_catalog"),
                )
                self.assertFalse(connection.autocommit)

    def test_failed_session_configuration_closes_and_does_not_cache_connection(self):
        connection = MagicMock()
        connection.closed = False
        connection.autocommit = False
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = RuntimeError("session initialization failed")
        with patch("app.database.connection.config", Config()):
            with patch("app.database.connection.psycopg2.connect", return_value=connection):
                database = DatabaseConnection()
                with self.assertRaisesRegex(RuntimeError, "initialization failed"):
                    database.connect()
                self.assertIsNone(database.connection)
                self.assertFalse(connection.autocommit)
                connection.close.assert_called_once()

    def test_invalid_configuration_does_not_call_driver(self):
        os.environ["POSTGRES_SSLMODE"] = "invalid"
        with patch("app.database.connection.config", Config()):
            with patch("app.database.connection.psycopg2.connect") as connect:
                with self.assertRaises(ValueError):
                    DatabaseConnection().connect()
                connect.assert_not_called()

    def test_alternative_env_file_can_be_loaded_without_cli_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "external-test.env"
            path.write_text("POSTGRES_USER=restricted_test\nPOSTGRES_SCHEMA=etl_private\n")
            environment = {
                name: value for name, value in os.environ.items()
                if not name.startswith("POSTGRES_")
            }
            environment["ETL_ENV_FILE"] = str(path)
            result = subprocess.run(
                [sys.executable, "-c", (
                    "from app.config.config import config; "
                    "assert config.POSTGRES_USER == 'restricted_test'; "
                    "assert config.POSTGRES_SCHEMA == 'etl_private'"
                )],
                env=environment, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_env_is_loaded_from_project_root_not_current_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("POSTGRES_USER=restricted_default\nETL_PAGE_SIZE=37\n")
            with patch.dict(os.environ, {}, clear=True):
                path = load_environment(root)
                self.assertEqual(path, root / ".env")
                self.assertEqual(Config().POSTGRES_USER, "restricted_default")
                self.assertEqual(Config().ETL_PAGE_SIZE, 37)

    def test_single_example_lists_every_application_setting_without_credentials(self):
        example = dotenv_values(PROJECT_ROOT / ".env.example")
        self.assertEqual(set(example), set(vars(Config())))
        self.assertEqual(len(example), 16)
        self.assertEqual(example["POSTGRES_SSLMODE"], "verify-full")
        self.assertEqual(example["POSTGRES_PASSWORD"], "PREENCHA_A_SENHA_DO_ETL_SUPABASE")
        for old in (".env.etl.example", ".env.supabase.example", ".env.supabase.etl.example"):
            self.assertFalse((PROJECT_ROOT / old).exists())

    def test_process_values_override_file_without_loading_other_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("POSTGRES_USER=file_user\nETL_PAGE_SIZE=37\n")
            (root / ".env.supabase").write_text("POSTGRES_USER=admin_must_not_load\n")
            with patch.dict(os.environ, {"POSTGRES_USER": "injected_user"}, clear=True):
                load_environment(root)
                self.assertEqual(Config().POSTGRES_USER, "injected_user")
                self.assertEqual(Config().ETL_PAGE_SIZE, 37)

    def test_private_profile_examples_are_complete_and_have_only_placeholder_passwords(self):
        names = ("supabase-admin", "local-admin", "local-etl")
        for name in names:
            with self.subTest(profile=name):
                values = dotenv_values(PROJECT_ROOT / "config-private" / f"{name}.env.example")
                self.assertEqual(set(values), set(vars(Config())))
                self.assertTrue(values["POSTGRES_PASSWORD"].startswith("PREENCHA_"))
                self.assertIn("SEU-PROJETO", values["FIREBASE_DATABASE_URL"])
                self.assertEqual(values["POSTGRES_SSLMODE"],
                                 "verify-full" if name == "supabase-admin" else "disable")

    def test_git_ignores_real_profiles_and_only_allows_the_three_named_examples(self):
        for name in ("supabase-admin", "local-admin", "local-etl"):
            for suffix, expected in ((".env", 0), (".env.example", 1)):
                result = subprocess.run(
                    ["git", "check-ignore", "--no-index", "--quiet", "--",
                     f"config-private/{name}{suffix}"],
                    cwd=PROJECT_ROOT, capture_output=True,
                )
                self.assertEqual(result.returncode, expected)
        for path in (".env", "config-private/extra-secret.env",
                     "config-private/unknown.env.example", "config-private/nested/secret.env"):
            result = subprocess.run(
                ["git", "check-ignore", "--no-index", "--quiet", "--", path],
                cwd=PROJECT_ROOT, capture_output=True,
            )
            self.assertEqual(result.returncode, 0)

    def test_external_file_replaces_default_instead_of_merging_admin_and_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("POSTGRES_USER=default_user\nETL_PAGE_SIZE=37\n")
            external = root / "maintenance.env"
            external.write_text("POSTGRES_USER=maintenance_user\n")
            with patch.dict(os.environ, {"ETL_ENV_FILE": str(external)}, clear=True):
                self.assertEqual(load_environment(root), external)
                self.assertEqual(Config().POSTGRES_USER, "maintenance_user")
                self.assertEqual(Config().ETL_PAGE_SIZE, 500)

    def test_missing_default_allows_configuration_injected_by_deploy(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"POSTGRES_USER": "injected"}, clear=True):
                load_environment(Path(directory))
                self.assertEqual(Config().POSTGRES_USER, "injected")

    def test_missing_explicit_file_fails_instead_of_falling_back_to_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"ETL_ENV_FILE": "missing.env"}, clear=True):
                with self.assertRaisesRegex(ValueError, "ETL_ENV_FILE"):
                    load_environment(Path(directory))

    def test_import_from_another_directory_still_selects_repository_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                name: value for name, value in os.environ.items()
                if not name.startswith(("POSTGRES_", "FIREBASE_", "ETL_"))
            }
            environment["PYTHONPATH"] = str(PROJECT_ROOT)
            result = subprocess.run(
                [sys.executable, "-c", (
                    "from app.config.config import ENV_FILE, PROJECT_ROOT; "
                    "assert ENV_FILE == PROJECT_ROOT / '.env'"
                )],
                cwd=directory, env=environment, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rehearsal_child_does_not_inherit_active_supabase_configuration(self):
        from app.operations.rehearse import child
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "disposable.env"
            profile.write_text("POSTGRES_HOST=127.0.0.1\n")
            with patch.dict(os.environ, {
                "POSTGRES_HOST": "active-supabase",
                "FIREBASE_DATABASE_URL": "active-source",
                "ETL_ENV_FILE": "old-profile",
                "ETL_PAGE_SIZE": "1",
                "ETL_LOOKBACK_RECORDS": "0",
                "PATH": os.environ.get("PATH", ""),
            }, clear=True), patch("app.operations.rehearse.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "completed"
                self.assertEqual(child(profile, "app.operations.rehearse", "actor"), "completed")
            environment = run.call_args.kwargs["env"]
            self.assertEqual(environment["ETL_ENV_FILE"], str(profile))
            self.assertNotIn("POSTGRES_HOST", environment)
            self.assertNotIn("FIREBASE_DATABASE_URL", environment)
            self.assertNotIn("ETL_PAGE_SIZE", environment)
            self.assertNotIn("ETL_LOOKBACK_RECORDS", environment)
