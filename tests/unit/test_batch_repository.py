"""Contrato de lote/contagem/transação com driver SQL simulado."""

from datetime import datetime
import unittest
from unittest.mock import MagicMock, patch

from app.models.sensor import Sensor
from app.models.buoy import Buoy
from app.repository.base import BATCH_SIZE
from app.repository.sensor_repository import SensorRepository
from app.repository.buoy_repository import BuoyRepository


class TestBatchRepository(unittest.TestCase):
    def setUp(self):
        self.database = MagicMock()
        self.cursor = (
            self.database.connect.return_value.cursor.return_value.__enter__.return_value
        )
        self.repository = SensorRepository(self.database)
        self.execute_patch = patch("app.repository.base.execute_values")
        self.execute = self.execute_patch.start()
        self.addCleanup(self.execute_patch.stop)

    @staticmethod
    def objects(count):
        return [
            Sensor(str(i), "EST_TEST", datetime(2026, 8, 20))
            for i in range(count)
        ]

    def test_empty_batch_does_not_connect(self):
        self.assertEqual(self.repository.insert_many([]), 0)
        self.database.connect.assert_not_called()

    def test_multiple_pages_count_returned_rows_and_commit_once(self):
        self.cursor.fetchall.side_effect = [
            [("id",)] * BATCH_SIZE, [("id",)] * 2,
        ]
        self.assertEqual(
            self.repository.insert_many(self.objects(BATCH_SIZE + 3)),
            BATCH_SIZE + 2,
        )
        self.assertEqual(self.execute.call_count, 2)
        for call, size in zip(self.execute.call_args_list, (BATCH_SIZE, 3)):
            self.assertEqual(len(call.args[2]), size)
            self.assertEqual(call.kwargs["page_size"], size)
            self.assertIn("ON CONFLICT (sensor_id, firebase_id)", call.args[1])
            self.assertIn("DO NOTHING", call.args[1])
        self.database.commit.assert_called_once()
        self.database.rollback.assert_not_called()

    def test_second_page_failure_rolls_back_entire_call(self):
        self.cursor.fetchall.return_value = [("id",)] * BATCH_SIZE
        self.execute.side_effect = [None, RuntimeError("segunda página")]
        with self.assertRaisesRegex(RuntimeError, "segunda página"):
            self.repository.insert_many(self.objects(BATCH_SIZE + 1))
        self.assertEqual(self.execute.call_count, 2)
        self.database.rollback.assert_called_once()
        self.database.commit.assert_not_called()

    def test_commit_failure_also_rolls_back(self):
        self.cursor.fetchall.return_value = [("id",)]
        self.database.commit.side_effect = RuntimeError("commit")
        with self.assertRaisesRegex(RuntimeError, "commit"):
            self.repository.insert_many(self.objects(1))
        self.database.rollback.assert_called_once()

    def test_existing_rows_return_zero(self):
        self.cursor.fetchall.return_value = []
        self.assertEqual(self.repository.insert_many(self.objects(2)), 0)
        self.database.commit.assert_called_once()

    def test_buoys_use_device_and_firebase_id_as_conflict_target(self):
        repository = BuoyRepository(self.database)
        repository.insert(Buoy("-001", "BOIA_TEST", datetime(2026, 8, 20)))
        query = self.execute.call_args.args[1]
        self.assertIn("ON CONFLICT (buoy_id, firebase_id)", query)
        self.assertIn("DO NOTHING", query)

    def test_single_insert_preserves_boolean_api(self):
        with patch.object(self.repository, "insert_many", side_effect=[1, 0]):
            obj = self.objects(1)[0]
            self.assertIs(self.repository.insert(obj), True)
            self.assertIs(self.repository.insert(obj), False)
