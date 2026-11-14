"""Cenários incrementais determinísticos, sem serviços reais."""

import unittest
from unittest.mock import Mock, patch

from app.worker.etl_worker import ETLWorker


class TestETLWorker(unittest.TestCase):
    def setUp(self):
        self.firebase_patch = patch("app.worker.etl_worker.FirebaseClient")
        self.database_patch = patch("app.worker.etl_worker.DatabaseConnection")
        self.firebase_patch.start()
        self.database_patch.start()
        self.addCleanup(self.firebase_patch.stop)
        self.addCleanup(self.database_patch.stop)
        self.worker = ETLWorker()
        self.worker.logger = Mock()
        self.worker.checkpoints = Mock()
        self.worker.checkpoints.get.return_value = None
        self.worker.sensor_repository = Mock()
        self.worker.sensor_repository.insert_many.side_effect = len
        self.root = self.worker.firebase.sensors.return_value
        self.root.get.return_value = {"EST_TEST": True}
        self.query = (
            self.worker.firebase.sensor_data.return_value.order_by_key.return_value
        )
        self.query.start_at.return_value = self.query
        self.query.get.return_value = {}

    @staticmethod
    def record(value=25):
        return {"hora": "2026-08-20 17:29:06", "temperatura": value}

    def test_initial_load_commits_before_checkpoint(self):
        self.query.get.return_value = {
            "-002": self.record(26), "-001": self.record(25),
        }
        order = Mock()
        order.attach_mock(self.worker.sensor_repository.insert_many, "insert")
        order.attach_mock(self.worker.checkpoints.set, "checkpoint")

        self.assertEqual(self.worker.process_sensors(), (2, 2, 0, 0))

        self.root.get.assert_called_once_with(shallow=True)
        self.query.start_at.assert_not_called()
        self.assertEqual([call[0] for call in order.mock_calls], [
            "insert", "checkpoint",
        ])
        self.worker.checkpoints.set.assert_called_once_with(
            "sensores", "EST_TEST", "-002",
        )
        objects = self.worker.sensor_repository.insert_many.call_args.args[0]
        self.assertEqual({obj.firebase_id for obj in objects}, {"-001", "-002"})

    def test_start_at_boundary_is_skipped(self):
        self.worker.checkpoints.get.return_value = "-002"
        self.query.get.return_value = {
            "-001": self.record(), "-002": self.record(), "-003": self.record(),
        }
        self.assertEqual(self.worker.process_sensors(), (1, 1, 0, 0))
        self.query.start_at.assert_called_once_with("-002")
        objects = self.worker.sensor_repository.insert_many.call_args.args[0]
        self.assertEqual([obj.firebase_id for obj in objects], ["-003"])

    def test_updated_checkpoint_accepts_zero_records(self):
        self.worker.checkpoints.get.return_value = "-002"
        self.query.get.return_value = {"-002": self.record()}
        self.assertEqual(self.worker.process_sensors(), (0, 0, 0, 0))
        self.worker.sensor_repository.insert_many.assert_not_called()
        self.worker.checkpoints.set.assert_not_called()

    def test_database_failure_does_not_advance_checkpoint(self):
        self.worker.checkpoints.get.return_value = "-001"
        self.query.get.return_value = {
            "-002": self.record(), "-003": self.record(),
        }
        self.worker.sensor_repository.insert_many.side_effect = RuntimeError("DB")
        self.assertEqual(self.worker.process_sensors(), (2, 0, 0, 2))
        self.worker.checkpoints.set.assert_not_called()

        self.worker.sensor_repository.insert_many.side_effect = len
        self.assertEqual(self.worker.process_sensors(), (2, 2, 0, 0))
        self.worker.checkpoints.set.assert_called_once_with(
            "sensores", "EST_TEST", "-003",
        )

    def test_normalization_error_is_counted_and_checkpoint_advances(self):
        self.query.get.return_value = {
            "-001": self.record(), "-002": self.record("inválido"),
        }
        self.assertEqual(self.worker.process_sensors(), (2, 1, 0, 1))
        self.worker.checkpoints.set.assert_called_once_with(
            "sensores", "EST_TEST", "-002",
        )

    def test_checkpoint_failure_replays_existing_records_safely(self):
        self.query.get.return_value = {"-001": self.record()}
        # Simula o contrato append-only da persistência, não o driver SQL.
        stored = set()

        def insert(objects):
            before = len(stored)
            stored.update((obj.firebase_id, obj.timestamp) for obj in objects)
            return len(stored) - before

        self.worker.sensor_repository.insert_many.side_effect = insert
        self.worker.checkpoints.set.side_effect = RuntimeError("checkpoint")
        self.assertEqual(self.worker.process_sensors(), (1, 1, 0, 0))
        self.worker.checkpoints.set.side_effect = None
        self.assertEqual(self.worker.process_sensors(), (1, 0, 1, 0))
        self.assertEqual(len(stored), 1)

    def test_buoys_use_their_own_source_and_repository(self):
        self.worker.firebase.buoys.return_value.get.return_value = {"BOIA_TEST": True}
        query = self.worker.firebase.buoy_data.return_value.order_by_key.return_value
        query.get.return_value = {"-001": {"hora": "2026-08-20 17:29:06", "ph": 7}}
        self.worker.buoy_repository = Mock()
        self.worker.buoy_repository.insert_many.return_value = 1
        self.assertEqual(self.worker.process_buoys(), (1, 1, 0, 0))
        self.worker.checkpoints.get.assert_called_once_with("boias", "BOIA_TEST")
        self.worker.checkpoints.set.assert_called_once_with(
            "boias", "BOIA_TEST", "-001",
        )
        self.worker.sensor_repository.insert_many.assert_not_called()

    def test_run_once_allows_both_sources_to_be_up_to_date(self):
        with (
            patch.object(self.worker, "process_sensors", return_value=(0, 0, 0, 0)),
            patch.object(self.worker, "process_buoys", return_value=(0, 0, 0, 0)),
        ):
            self.assertEqual(self.worker.run_once(), ((0, 0, 0, 0), (0, 0, 0, 0)))
