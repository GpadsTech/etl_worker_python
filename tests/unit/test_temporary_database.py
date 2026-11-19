"""Garante o isolamento e a limpeza sem acessar PostgreSQL."""

import unittest
from unittest.mock import MagicMock, patch

from app.worker.etl_worker import ETLWorker
from tests.integration.temporary_database import (
    TemporaryDatabase,
    TemporaryDatabaseTestCase,
)


class TestTemporaryDatabase(unittest.TestCase):
    def setUp(self):
        session_patch = patch.object(TemporaryDatabase, "_configure_session")
        session_patch.start()
        self.addCleanup(session_patch.stop)
        self.connection = MagicMock()
        self.connection.closed = False
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.connect_patch = patch(
            "app.database.connection.psycopg2.connect", return_value=self.connection,
        )
        self.connect = self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)

    def test_creates_only_temporary_tables_without_public_search_path(self):
        database = TemporaryDatabase()
        self.assertIs(database.connect(), self.connection)
        statements = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertEqual(statements[0], "SET search_path TO pg_temp, pg_catalog;")
        self.assertEqual(len(statements), 5)
        for table, statement in zip(
            ("sensor_data", "buoy_data", "etl_checkpoint", "etl_rejections"), statements[1:],
        ):
            self.assertIn(f"CREATE TEMP TABLE {table}", statement)
            self.assertIn("ON COMMIT PRESERVE ROWS", statement)
            self.assertNotIn("public.", statement)
            self.assertNotIn("DELETE", statement)
            self.assertNotIn("TRUNCATE", statement)
        self.connection.commit.assert_called_once()

    def test_measurement_tables_use_device_and_reading_identity(self):
        TemporaryDatabase().connect()
        statements = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertIn("PRIMARY KEY (sensor_id, firebase_id)", statements[1])
        self.assertIn("PRIMARY KEY (buoy_id, firebase_id)", statements[2])

    def test_reuses_session_without_recreating_tables_after_commit_or_rollback(self):
        database = TemporaryDatabase()
        first = database.connect()
        database.commit()
        database.rollback()
        self.assertIs(database.connect(), first)
        self.connect.assert_called_once()
        self.assertEqual(self.cursor.execute.call_count, 5)

    def test_lost_session_does_not_reconnect_to_permanent_tables(self):
        database = TemporaryDatabase()
        database.connect()
        self.connection.closed = True
        with self.assertRaisesRegex(ConnectionError, "não é seguro reconectar"):
            database.connect()
        self.connect.assert_called_once()

    def test_failed_initialization_closes_session(self):
        self.cursor.execute.side_effect = RuntimeError("falha ao criar tabela")
        with self.assertRaisesRegex(RuntimeError, "falha ao criar tabela"):
            TemporaryDatabase().connect()
        self.connection.close.assert_called_once()
        self.connection.commit.assert_not_called()

    def test_testcase_closes_session_even_after_test_failure(self):
        class FailingCase(TemporaryDatabaseTestCase):
            def runTest(self):
                self.database.commit()
                self.fail("falha simulada")

        result = unittest.TestResult()
        FailingCase().run(result)
        self.assertEqual(len(result.failures), 1)
        self.connection.close.assert_called_once()

    def test_testcase_cleans_up_when_setup_fails(self):
        self.cursor.execute.side_effect = RuntimeError("preparação")

        class FailingSetup(TemporaryDatabaseTestCase):
            def runTest(self):
                raise AssertionError("não deve executar")

        result = unittest.TestResult()
        FailingSetup().run(result)
        self.assertEqual(len(result.errors), 1)
        self.connection.close.assert_called()

    def test_all_sql_writer_tests_use_isolated_base(self):
        from tests.integration.test_batch_transaction import TestBatchTransaction
        from tests.integration.test_buoy_repository import TestBuoyRepository
        from tests.integration.test_etl_buoy import TestETLBuoy
        from tests.integration.test_etl_sensor import TestETLSensor
        from tests.integration.test_etl_worker import TestETLWorker
        from tests.integration.test_idempotency import TestIdempotency
        from tests.integration.test_sensor_repository import TestSensorRepository
        from tests.integration.test_rejections import TestRejections
        from tests.integration.test_device_identity import TestDeviceIdentity
        from tests.integration.test_identity_migration import TestIdentityMigration

        for test_class in (
            TestBatchTransaction, TestBuoyRepository, TestETLBuoy, TestETLSensor,
            TestETLWorker, TestIdempotency, TestSensorRepository, TestRejections,
            TestDeviceIdentity, TestIdentityMigration,
        ):
            with self.subTest(test_class=test_class.__name__):
                self.assertTrue(issubclass(test_class, TemporaryDatabaseTestCase))

    def test_worker_repositories_share_the_temporary_session(self):
        database = TemporaryDatabase()
        database.connect()
        with patch("app.worker.etl_worker.DatabaseConnection", return_value=database):
            worker = ETLWorker()
        self.assertIs(worker.database, database)
        self.assertIs(worker.sensor_repository.database, database)
        self.assertIs(worker.buoy_repository.database, database)
        self.assertIs(worker.checkpoints.database, database)
        self.assertIs(worker.rejections.database, database)
