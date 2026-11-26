"""SQL real somente em tabelas TEMP; Firebase sempre simulado."""

from unittest.mock import Mock, patch

from app.models.rejection import Rejection
from app.repository.checkpoint_repository import CheckpointRepository
from app.repository.rejection_repository import RejectionRepository
from app.worker.etl_worker import ETLWorker
from tests.integration.gate import integration_test
from tests.integration.temporary_database import TemporaryDatabaseTestCase
from tests.legacy_paging import isolate_persistence


@integration_test
class TestRejections(TemporaryDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.repository = RejectionRepository(self.database)
        self.rejected = Rejection(
            "sensores", "EST_TEST", "-002",
            {"hora": "2026-08-20 17:29:06", "temperatura": "inválido"},
            "ValueError: temperatura",
        )

    def worker(self):
        with patch("app.worker.etl_worker.DatabaseConnection", return_value=self.database):
            worker = ETLWorker()
        worker.firebase = Mock()
        isolate_persistence(self, worker)
        worker.logger = Mock()
        return worker

    def state(self):
        with self.database.connect().cursor() as cursor:
            cursor.execute(
                "SELECT attempts, resolved_at IS NOT NULL, payload "
                "FROM pg_temp.etl_rejections"
            )
            return cursor.fetchall()

    def test_replay_upserts_single_rejection_and_tracks_attempts(self):
        self.repository.save_many([self.rejected])
        self.repository.save_many([self.rejected])
        self.assertEqual(self.repository.pending(), [self.rejected])
        self.assertEqual(self.state(), [(2, False, self.rejected.payload)])

    def test_second_page_failure_rolls_back_all_rejections(self):
        from app.repository.base import BATCH_SIZE
        from psycopg2.errors import CheckViolation

        rows = [
            Rejection("sensores", "EST_TEST", str(i), {}, "erro")
            for i in range(BATCH_SIZE)
        ]
        rows.append(Rejection("invalida", "EST_TEST", "fim", {}, "erro"))
        with self.assertRaises(CheckViolation):
            self.repository.save_many(rows)
        self.assertEqual(self.repository.pending(), [])

    def test_json_scalar_and_null_are_preserved(self):
        rows = [
            Rejection("boias", "BOIA_TEST", str(i), payload, "erro")
            for i, payload in enumerate((None, True, "inválido", [], 12))
        ]
        self.repository.save_many(rows)
        self.assertEqual(self.repository.pending(), rows)

    def test_filters_limit_and_resolution_exclude_unselected_records(self):
        buoy = Rejection("boias", "BOIA_TEST", "-001", {}, "erro")
        other = Rejection("sensores", "OUTRO", "-003", {}, "erro")
        self.repository.save_many([self.rejected, buoy, other])
        self.assertEqual(
            self.repository.pending(1, "sensores", "EST_TEST"), [self.rejected],
        )
        self.repository.mark_resolved(self.rejected)
        self.assertEqual(self.repository.pending(10, "sensores"), [other])
        self.assertEqual(self.repository.pending(10, "boias", "BOIA_TEST"), [buoy])

    def test_mixed_ingestion_saves_rejection_and_checkpoint_then_replays_safely(self):
        worker = self.worker()
        worker.firebase.sensors.return_value.get.return_value = {"EST_TEST": True}
        query = worker.firebase.sensor_data.return_value.order_by_key.return_value
        query.start_at.return_value = query
        query.get.return_value = {
            "-001": {"hora": "2026-08-20 17:29:06", "temperatura": 25},
            "-002": self.rejected.payload,
        }
        self.assertEqual(worker.process_sensors(), (2, 1, 0, 1))
        self.assertEqual(worker.checkpoints.get("sensores", "EST_TEST"), "-002")
        self.assertEqual(len(self.repository.pending()), 1)
        self.assertEqual(worker.process_sensors(), (0, 0, 0, 0))

    def test_rejection_failure_blocks_checkpoint_even_if_valid_data_commits(self):
        worker = self.worker()
        worker.firebase.sensors.return_value.get.return_value = {"EST_TEST": True}
        query = worker.firebase.sensor_data.return_value.order_by_key.return_value
        query.get.return_value = {
            "-001": {"hora": "2026-08-20 17:29:06", "temperatura": 25},
            "-002": self.rejected.payload,
        }
        with patch.object(worker.rejections, "save_many", side_effect=RuntimeError("DB")):
            self.assertEqual(worker.process_sensors(), (2, 1, 0, 1))
        self.assertIsNone(worker.checkpoints.get("sensores", "EST_TEST"))
        self.assertEqual(worker.process_sensors(), (2, 0, 1, 1))
        self.assertEqual(worker.checkpoints.get("sensores", "EST_TEST"), "-002")

    def test_sql_rejection_does_not_hold_back_valid_records_or_next_cycle(self):
        with self.database.connect().cursor() as cursor:
            cursor.execute(
                "ALTER TABLE pg_temp.sensor_data ADD CHECK (temperatura <= 50)"
            )
        self.database.commit()
        worker = self.worker()
        worker.firebase.sensors.return_value.get.return_value = {"EST_TEST": True}
        query = worker.firebase.sensor_data.return_value.order_by_key.return_value
        query.start_at.return_value = query
        payload = {"hora": "2026-08-20 17:29:06", "temperatura": 60}
        query.get.return_value = {
            "-001": {"hora": "2026-08-20 17:29:06", "temperatura": 25},
            "-002": payload,
            "-003": {"hora": "2026-08-20 17:29:06", "temperatura": 26},
        }
        self.assertEqual(worker.process_sensors(), (3, 2, 0, 1))
        self.assertEqual(worker.checkpoints.get("sensores", "EST_TEST"), "-003")
        rejected = self.repository.pending()
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].firebase_id, "-002")
        self.assertEqual(rejected[0].payload, payload)
        self.assertIn("CheckViolation", rejected[0].reason)
        query.get.return_value = {
            "-003": {"hora": "2026-08-20 17:29:06", "temperatura": 26},
            "-004": {"hora": "2026-08-20 17:29:06", "temperatura": 27},
        }
        self.assertEqual(worker.process_sensors(), (1, 1, 0, 0))
        self.assertEqual(worker.checkpoints.get("sensores", "EST_TEST"), "-004")
        self.assertEqual(len(self.repository.pending()), 1)

    def test_failed_retry_remains_pending_then_corrected_firebase_resolves(self):
        self.repository.save_many([self.rejected])
        checkpoints = CheckpointRepository(self.database)
        checkpoints.set("sensores", "EST_TEST", "-010")
        worker = self.worker()
        self.assertEqual(worker.reprocess_rejections(), (1, 0, 0, 1))
        self.assertEqual(self.state(), [(2, False, self.rejected.payload)])
        worker.firebase.sensor_data.return_value.child.return_value.get.return_value = {
            "hora": "2026-08-20 17:29:06", "temperatura": 25,
        }
        self.assertEqual(
            worker.reprocess_rejections(refresh_from_firebase=True),
            (1, 1, 0, 0),
        )
        self.assertEqual(self.repository.pending(), [])
        self.assertEqual(self.state(), [(3, True, self.rejected.payload)])
        self.assertEqual(checkpoints.get("sensores", "EST_TEST"), "-010")

    def test_commit_before_resolution_failure_allows_duplicate_safe_retry(self):
        self.rejected.payload = {"hora": "2026-08-20 17:29:06", "temperatura": 25}
        self.repository.save_many([self.rejected])
        worker = self.worker()
        with patch.object(worker.rejections, "mark_resolved", side_effect=RuntimeError("DB")):
            with self.assertRaises(RuntimeError):
                worker.reprocess_rejections()
        self.assertEqual(len(self.repository.pending()), 1)
        self.assertEqual(worker.reprocess_rejections(), (1, 0, 1, 0))
        self.assertEqual(self.repository.pending(), [])
