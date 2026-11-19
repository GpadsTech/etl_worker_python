"""Configuração de conexão sem acessar serviços ou registrar credenciais."""

import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from app.config.config import Config
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
            path = Path(directory) / ".env.etl"
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
