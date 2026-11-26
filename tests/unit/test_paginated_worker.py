"""Worker com consultas limitadas reais do simulador e storage em memória."""

import unittest
from unittest.mock import Mock, patch

from app.worker.etl_worker import ETLWorker
from tests.pagination_scenarios import PaginationScenarios


class TestPaginatedWorker(PaginationScenarios, unittest.TestCase):
    def setUp(self):
        self.rows, self.cursors, self.rejects = {}, {}, {}

    def new_worker(self):
        with patch("app.worker.etl_worker.DatabaseConnection"), \
                patch("app.worker.etl_worker.FirebaseClient"):
            worker = ETLWorker()
        worker.logger = Mock()
        worker.checkpoints = Mock()
        worker.checkpoints.get.side_effect = lambda s, d: self.cursors.get((s, d))
        worker.checkpoints.set.side_effect = lambda s, d, k: self.cursors.update({(s, d): k})
        worker.sensor_repository = Mock()

        def insert(objects):
            created = 0
            for obj in objects:
                identity = (obj.sensor_id, obj.firebase_id)
                if identity not in self.rows:
                    self.rows[identity] = obj
                    created += 1
            return created

        worker.sensor_repository.insert_many.side_effect = insert
        worker.sensor_repository.existing_ids.side_effect = lambda d, ids: {
            key for key in ids if (d, key) in self.rows
        }
        worker.rejections = Mock()
        worker.rejections.save_many.side_effect = lambda items: self.rejects.update({
            (r.source, r.device_id, r.firebase_id): r for r in items
        })
        worker.rejections.existing_ids.side_effect = lambda s, d, ids: {
            key for key in ids if (s, d, key) in self.rejects
        }
        worker.rejections.pending.side_effect = lambda: list(self.rejects.values())
        return worker

    def count(self):
        return len(self.rows)

    def test_lookback_does_not_silently_correct_accepted_measurement(self):
        from tests.unit.test_pagination import key
        from tests.pagination_scenarios import record
        worker = self.prepare_source()
        worker.process_sensors()
        self.records[key(4)] = record(99)
        worker.process_sensors()
        self.assertEqual(self.rows[("EST", key(4))].temperatura, 4)
