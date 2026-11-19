"""Exclusão mútua por sessão, sem acessar PostgreSQL ou Firebase reais."""

import unittest
from unittest.mock import MagicMock, Mock, patch

from psycopg2 import OperationalError

from app.database.connection import (
    DatabaseConnection,
    ETL_LOCK_KEY,
    WorkerAlreadyRunningError,
    WorkerLockLostError,
)
from app.worker.etl_worker import ETLWorker


class TestWorkerLock(unittest.TestCase):
    def setUp(self):
        self.connection = self.session()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        connect_patch = patch(
            "app.database.connection.psycopg2.connect", return_value=self.connection,
        )
        self.connect = connect_patch.start()
        self.addCleanup(connect_patch.stop)
        self.database = DatabaseConnection()
        session_patch = patch.object(DatabaseConnection, "_configure_session")
        session_patch.start()
        self.addCleanup(session_patch.stop)

    @staticmethod
    def session():
        connection = MagicMock()
        connection.closed = False
        connection.close.side_effect = lambda: setattr(connection, "closed", True)
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (True,)
        return connection

    def statements(self):
        return [call.args[0] for call in self.cursor.execute.call_args_list]

    def worker(self):
        with patch("app.worker.etl_worker.DatabaseConnection", return_value=self.database):
            worker = ETLWorker()
        worker.firebase = Mock()
        worker.logger = Mock()
        return worker

    def test_key_is_stable_positive_bigint(self):
        self.assertEqual(ETL_LOCK_KEY, int.from_bytes(b"MORHINGA", "big"))
        self.assertLess(ETL_LOCK_KEY, 2 ** 63)

    def test_acquires_and_releases_same_key_on_same_session(self):
        with self.database.exclusive():
            self.assertIs(self.database.connect(), self.connection)
            self.assertEqual(self.database._exclusive_depth, 1)
        self.assertEqual(self.statements(), [
            "SELECT pg_try_advisory_lock(%s);",
            "SELECT pg_advisory_unlock(%s);",
        ])
        for call in self.cursor.execute.call_args_list:
            self.assertEqual(call.args[1], (ETL_LOCK_KEY,))
        self.connect.assert_called_once()
        self.assertEqual(self.connection.commit.call_count, 2)
        self.connection.rollback.assert_called_once()
        self.connection.close.assert_not_called()
        self.assertEqual(self.database._exclusive_depth, 0)
        self.assertIsNone(self.database._lock_connection)

    def test_busy_does_not_enter_body_or_unlock_another_session(self):
        self.cursor.fetchone.return_value = (False,)
        body = Mock()
        with self.assertRaises(WorkerAlreadyRunningError):
            with self.database.exclusive():
                body()
        body.assert_not_called()
        self.assertEqual(self.statements(), ["SELECT pg_try_advisory_lock(%s);"])
        self.assertEqual(self.database._exclusive_depth, 0)

    def test_nested_calls_do_not_stack_postgres_session_locks(self):
        with self.database.exclusive():
            with self.database.exclusive():
                self.assertEqual(self.database._exclusive_depth, 2)
            self.assertEqual(self.database._exclusive_depth, 1)
        self.assertEqual(self.cursor.execute.call_count, 2)

    def test_commits_and_rollbacks_do_not_reacquire_or_release_early(self):
        with self.database.exclusive():
            self.database.commit()
            self.database.rollback()
            self.assertEqual(self.statements(), ["SELECT pg_try_advisory_lock(%s);"])
        self.assertEqual(self.cursor.execute.call_count, 2)

    def test_body_failure_releases_and_propagates(self):
        with self.assertRaisesRegex(ValueError, "registro"):
            with self.database.exclusive():
                raise ValueError("registro")
        self.assertIn("SELECT pg_advisory_unlock(%s);", self.statements())
        self.assertEqual(self.database._exclusive_depth, 0)

    def test_keyboard_interrupt_releases(self):
        with self.assertRaises(KeyboardInterrupt):
            with self.database.exclusive():
                raise KeyboardInterrupt
        self.assertIn("SELECT pg_advisory_unlock(%s);", self.statements())

    def test_lost_session_prohibits_connect_commit_and_rollback(self):
        with self.assertRaises(WorkerLockLostError):
            with self.database.exclusive():
                self.connection.closed = True
                for operation in (
                    self.database.connect, self.database.commit, self.database.rollback,
                ):
                    with self.assertRaises(WorkerLockLostError):
                        operation()
        self.connect.assert_called_once()
        self.assertEqual(self.database._exclusive_depth, 0)

    def test_only_a_new_operation_can_reconnect_and_reacquire(self):
        replacement = self.session()
        self.connect.side_effect = [self.connection, replacement]
        with self.assertRaises(WorkerLockLostError):
            with self.database.exclusive():
                self.connection.closed = True
                self.database.connect()
        with self.database.exclusive():
            self.assertIs(self.database.connect(), replacement)
        replacement_cursor = replacement.cursor.return_value.__enter__.return_value
        self.assertEqual(self.connect.call_count, 2)
        self.assertEqual(replacement_cursor.execute.call_count, 2)
        self.assertIn(
            "pg_try_advisory_lock", replacement_cursor.execute.call_args_list[0].args[0],
        )

    def test_replaced_connection_is_not_used_and_both_sessions_close(self):
        replacement = self.session()
        with self.assertRaises(WorkerLockLostError):
            with self.database.exclusive():
                self.database.connection = replacement
                self.database.connect()
        self.connection.close.assert_called_once()
        replacement.close.assert_called_once()
        replacement.cursor.assert_not_called()

    def test_acquisition_query_failure_closes_session(self):
        self.cursor.execute.side_effect = OperationalError("offline")
        with self.assertRaises(OperationalError):
            with self.database.exclusive():
                self.fail("Não deve entrar.")
        self.connection.close.assert_called_once()

    def test_acquisition_commit_failure_closes_possible_lock_holder(self):
        self.connection.commit.side_effect = OperationalError("commit")
        with self.assertRaises(OperationalError):
            with self.database.exclusive():
                self.fail("Não deve entrar.")
        self.connection.close.assert_called_once()

    def test_unlock_query_failure_closes_session_and_resets_guard(self):
        self.cursor.execute.side_effect = [None, OperationalError("unlock")]
        with self.assertRaises(OperationalError):
            with self.database.exclusive():
                pass
        self.connection.close.assert_called_once()
        self.assertEqual(self.database._exclusive_depth, 0)

    def test_unlock_false_is_a_lost_lock_not_success(self):
        self.cursor.fetchone.side_effect = [(True,), (False,)]
        with self.assertRaises(WorkerLockLostError):
            with self.database.exclusive():
                pass
        self.connection.close.assert_called_once()

    def test_cleanup_rollback_failure_closes_session(self):
        self.connection.rollback.side_effect = OperationalError("rollback")
        with self.assertRaises(OperationalError):
            with self.database.exclusive():
                pass
        self.connection.close.assert_called_once()
        self.assertEqual(self.database._exclusive_depth, 0)

    def test_busy_protects_all_public_worker_entry_points_before_firebase(self):
        worker = self.worker()
        self.cursor.fetchone.return_value = (False,)
        for operation in (
            worker.run_once, worker.process_sensors,
            worker.process_buoys, worker.reprocess_rejections,
        ):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(WorkerAlreadyRunningError):
                    operation()
        self.assertEqual(worker.firebase.mock_calls, [])

    def test_one_lock_covers_entire_cycle_including_both_sources(self):
        worker = self.worker()
        worker.firebase.sensors.return_value.get.return_value = {}
        worker.firebase.buoys.return_value.get.return_value = {}
        self.assertEqual(worker.run_once(), ((0, 0, 0, 0), (0, 0, 0, 0)))
        self.assertEqual(self.cursor.execute.call_count, 2)
        worker.firebase.sensors.return_value.get.assert_called_once()
        worker.firebase.buoys.return_value.get.assert_called_once()

    def test_reprocessing_is_inside_guard(self):
        worker = self.worker()
        worker.rejections = Mock()

        def pending(*args):
            self.assertEqual(self.database._exclusive_depth, 1)
            return []

        worker.rejections.pending.side_effect = pending
        self.assertEqual(worker.reprocess_rejections(), (0, 0, 0, 0))
        self.assertEqual(self.cursor.execute.call_count, 2)
