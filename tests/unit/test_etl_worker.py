"""Cenários incrementais determinísticos, sem serviços reais."""

import unittest
from unittest.mock import Mock, patch

from psycopg2 import DataError, IntegrityError, OperationalError

from app.worker.etl_worker import ETLWorker
from app.models.rejection import Rejection
from app.database.connection import WorkerLockLostError


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
        self.worker.rejections = Mock()
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
        rejected = self.worker.rejections.save_many.call_args.args[0]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].source, "sensores")
        self.assertEqual(rejected[0].device_id, "EST_TEST")
        self.assertEqual(rejected[0].firebase_id, "-002")
        self.assertEqual(rejected[0].payload, self.record("inválido"))
        self.assertIn("ValueError", rejected[0].reason)

    def test_checkpoint_follows_both_rejection_and_data_commits(self):
        self.query.get.return_value = {
            "-001": self.record(), "-002": self.record("inválido"),
        }
        order = Mock()
        order.attach_mock(self.worker.rejections.save_many, "reject")
        order.attach_mock(self.worker.sensor_repository.insert_many, "insert")
        order.attach_mock(self.worker.checkpoints.set, "checkpoint")
        self.worker.process_sensors()
        self.assertEqual(
            [call[0] for call in order.mock_calls],
            ["insert", "reject", "checkpoint"],
        )

    def test_rejection_save_failure_blocks_checkpoint_and_keeps_counts(self):
        self.query.get.return_value = {
            "-001": self.record(), "-002": self.record("inválido"),
        }
        self.worker.rejections.save_many.side_effect = RuntimeError("DB")
        self.assertEqual(self.worker.process_sensors(), (2, 1, 0, 1))
        self.worker.checkpoints.set.assert_not_called()

        # Próxima rodada relê os registros, sem ter perdido a rejeição.
        self.worker.rejections.save_many.side_effect = None
        self.worker.sensor_repository.insert_many.return_value = 0
        self.worker.sensor_repository.insert_many.side_effect = None
        self.assertEqual(self.worker.process_sensors(), (2, 0, 1, 1))
        self.worker.checkpoints.set.assert_called_once_with(
            "sensores", "EST_TEST", "-002",
        )

    def test_only_invalid_records_are_saved_before_checkpoint(self):
        self.query.get.return_value = {"-001": self.record("inválido")}
        self.assertEqual(self.worker.process_sensors(), (1, 0, 0, 1))
        self.worker.rejections.save_many.assert_called_once()
        self.worker.sensor_repository.insert_many.assert_not_called()
        self.worker.checkpoints.set.assert_called_once()

    def test_only_invalid_records_cannot_advance_if_save_fails(self):
        self.query.get.return_value = {"-001": self.record("inválido")}
        self.worker.rejections.save_many.side_effect = RuntimeError("DB")
        self.assertEqual(self.worker.process_sensors(), (1, 0, 0, 1))
        self.worker.checkpoints.set.assert_not_called()

    def test_non_object_payloads_are_preserved_not_silently_skipped(self):
        for payload in ("inválido", 12, True, [], None):
            with self.subTest(payload=payload):
                self.query.get.return_value = {"-001": payload}
                self.assertEqual(self.worker.process_sensors(), (1, 0, 0, 1))
                rejected = self.worker.rejections.save_many.call_args.args[0][0]
                self.assertEqual(rejected.payload, payload)

    def test_invalid_boundary_is_not_rejected_again(self):
        self.worker.checkpoints.get.return_value = "-002"
        self.query.get.return_value = {"-002": "inválido"}
        self.assertEqual(self.worker.process_sensors(), (0, 0, 0, 0))
        self.worker.rejections.save_many.assert_not_called()

    def test_data_failure_keeps_checkpoint_even_after_rejections_saved(self):
        self.query.get.return_value = {
            "-001": self.record(), "-002": self.record("inválido"),
        }
        self.worker.sensor_repository.insert_many.side_effect = RuntimeError("DB")
        self.assertEqual(self.worker.process_sensors(), (2, 0, 0, 2))
        self.worker.rejections.save_many.assert_called_once()
        self.worker.checkpoints.set.assert_not_called()

    def test_no_rejections_does_not_write_rejections(self):
        self.query.get.return_value = {"-001": self.record()}
        self.worker.process_sensors()
        self.worker.rejections.save_many.assert_not_called()

    def test_sql_record_error_is_rejected_and_rest_commits_with_checkpoint(self):
        self.query.get.return_value = {
            "-001": self.record(24),
            "-002": self.record(25),
            "-003": self.record(26),
        }
        for error_type in (DataError, IntegrityError):
            with self.subTest(error_type=error_type.__name__):
                self.worker.sensor_repository.insert_many.side_effect = error_type("lote")
                self.worker.sensor_repository.insert.side_effect = [
                    True, error_type("registro"), True,
                ]
                self.assertEqual(self.worker.process_sensors(), (3, 2, 0, 1))
                rejected = self.worker.rejections.save_many.call_args.args[0]
                self.assertEqual(len(rejected), 1)
                self.assertEqual(rejected[0].firebase_id, "-002")
                self.assertEqual(rejected[0].payload, self.record(25))
                self.assertIn("Persistência", rejected[0].reason)
                self.worker.checkpoints.set.assert_called_with(
                    "sensores", "EST_TEST", "-003",
                )

    def test_normalization_and_sql_rejections_are_saved_together(self):
        self.query.get.return_value = {
            "-001": self.record("inválido"),
            "-002": self.record(25),
            "-003": self.record(26),
        }
        self.worker.sensor_repository.insert_many.side_effect = IntegrityError("lote")
        self.worker.sensor_repository.insert.side_effect = [IntegrityError("registro"), True]
        self.assertEqual(self.worker.process_sensors(), (3, 1, 0, 2))
        rejected = self.worker.rejections.save_many.call_args.args[0]
        self.assertEqual({item.firebase_id for item in rejected}, {"-001", "-002"})
        self.worker.rejections.save_many.assert_called_once()
        self.worker.checkpoints.set.assert_called_once_with(
            "sensores", "EST_TEST", "-003",
        )

    def test_entire_sql_batch_can_be_rejected_without_blocking_checkpoint(self):
        self.query.get.return_value = {"-001": self.record(), "-002": self.record()}
        self.worker.sensor_repository.insert_many.side_effect = DataError("lote")
        self.worker.sensor_repository.insert.side_effect = DataError("registro")
        self.assertEqual(self.worker.process_sensors(), (2, 0, 0, 2))
        rejected = self.worker.rejections.save_many.call_args.args[0]
        self.assertEqual(len(rejected), 2)
        self.worker.checkpoints.set.assert_called_once_with(
            "sensores", "EST_TEST", "-002",
        )

    def test_sql_fallback_counts_existing_and_new_records(self):
        self.query.get.return_value = {
            "-001": self.record(), "-002": self.record(), "-003": self.record(),
        }
        self.worker.sensor_repository.insert_many.side_effect = DataError("lote")
        self.worker.sensor_repository.insert.side_effect = [False, DataError("erro"), True]
        self.assertEqual(self.worker.process_sensors(), (3, 1, 1, 1))
        self.worker.checkpoints.set.assert_called_once()

    def test_sql_rejection_not_saved_cannot_advance_checkpoint(self):
        self.query.get.return_value = {"-001": self.record(), "-002": self.record()}
        self.worker.sensor_repository.insert_many.side_effect = IntegrityError("lote")
        self.worker.sensor_repository.insert.side_effect = [True, IntegrityError("erro")]
        self.worker.rejections.save_many.side_effect = RuntimeError("DB")
        self.assertEqual(self.worker.process_sensors(), (2, 1, 0, 1))
        self.worker.checkpoints.set.assert_not_called()

    def test_operational_batch_failure_is_not_misclassified_as_invalid_data(self):
        self.query.get.return_value = {"-001": self.record()}
        self.worker.sensor_repository.insert_many.side_effect = OperationalError("offline")
        self.assertEqual(self.worker.process_sensors(), (1, 0, 0, 1))
        self.worker.sensor_repository.insert.assert_not_called()
        self.worker.rejections.save_many.assert_not_called()
        self.worker.checkpoints.set.assert_not_called()

    def test_lost_lock_aborts_cycle_before_rejections_or_checkpoint(self):
        self.query.get.return_value = {
            "-001": self.record(), "-002": self.record("inválido"),
        }
        self.worker.sensor_repository.insert_many.side_effect = WorkerLockLostError()
        with self.assertRaises(WorkerLockLostError):
            self.worker.process_sensors()
        self.worker.rejections.save_many.assert_not_called()
        self.worker.checkpoints.set.assert_not_called()

    def test_lost_lock_during_fallback_aborts_remaining_records(self):
        self.query.get.return_value = {"-001": self.record(), "-002": self.record()}
        self.worker.sensor_repository.insert_many.side_effect = DataError("lote")
        self.worker.sensor_repository.insert.side_effect = WorkerLockLostError()
        with self.assertRaises(WorkerLockLostError):
            self.worker.process_sensors()
        self.worker.sensor_repository.insert.assert_called_once()
        self.worker.checkpoints.set.assert_not_called()

    def test_lost_lock_during_reprocessing_is_not_a_rejected_record(self):
        self.worker.rejections.pending.return_value = [self.rejection()]
        self.worker.sensor_repository.insert.side_effect = WorkerLockLostError()
        with self.assertRaises(WorkerLockLostError):
            self.worker.reprocess_rejections()
        self.worker.rejections.mark_failed.assert_not_called()
        self.worker.rejections.mark_resolved.assert_not_called()

    def test_operational_failure_during_fallback_keeps_other_results_and_continues(self):
        self.query.get.return_value = {
            "-001": self.record(), "-002": self.record(), "-003": self.record(),
        }
        self.worker.sensor_repository.insert_many.side_effect = DataError("lote")
        self.worker.sensor_repository.insert.side_effect = [
            True, OperationalError("rede"), True,
        ]
        self.assertEqual(self.worker.process_sensors(), (3, 2, 0, 1))
        self.assertEqual(self.worker.sensor_repository.insert.call_count, 3)
        self.worker.rejections.save_many.assert_not_called()
        self.worker.checkpoints.set.assert_not_called()

    def test_rejection_does_not_require_manual_resolution_to_read_next_cycle(self):
        self.query.get.return_value = {
            "-001": self.record("inválido"), "-002": self.record(25),
        }
        self.assertEqual(self.worker.process_sensors(), (2, 1, 0, 1))
        self.worker.checkpoints.get.return_value = "-002"
        self.query.get.return_value = {"-002": self.record(25), "-003": self.record(26)}
        self.assertEqual(self.worker.process_sensors(), (1, 1, 0, 0))
        self.worker.checkpoints.set.assert_called_with("sensores", "EST_TEST", "-003")
        self.worker.rejections.pending.assert_not_called()
        self.worker.rejections.mark_resolved.assert_not_called()

    def test_normalization_logs_do_not_include_payload_or_reason(self):
        self.query.get.return_value = {"-001": self.record("segredo-do-payload")}
        self.worker.process_sensors()
        messages = str(self.worker.logger.error.call_args_list)
        self.assertNotIn("segredo-do-payload", messages)
        self.assertIn("ValueError", messages)

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

    def rejection(self, payload=None):
        return Rejection(
            "sensores", "EST_TEST", "-001",
            self.record() if payload is None else payload, "Erro anterior",
        )

    def test_reprocess_saved_payload_commits_before_resolution(self):
        rejected = self.rejection()
        self.worker.rejections.pending.return_value = [rejected]
        self.worker.sensor_repository.insert.return_value = True
        order = Mock()
        order.attach_mock(self.worker.sensor_repository.insert, "insert")
        order.attach_mock(self.worker.rejections.mark_resolved, "resolve")

        self.assertEqual(
            self.worker.reprocess_rejections(10, "sensores", "EST_TEST"),
            (1, 1, 0, 0),
        )
        self.worker.rejections.pending.assert_called_once_with(
            10, "sensores", "EST_TEST",
        )
        self.assertEqual(
            [call[0] for call in order.mock_calls], ["insert", "resolve"],
        )
        self.worker.rejections.mark_resolved.assert_called_once_with(rejected)
        self.worker.checkpoints.set.assert_not_called()
        self.worker.firebase.sensor_data.assert_not_called()

    def test_reprocess_refresh_uses_corrected_firebase_without_changing_original(self):
        rejected = self.rejection(self.record("inválido"))
        self.worker.rejections.pending.return_value = [rejected]
        self.worker.firebase.sensor_data.return_value.child.return_value.get.return_value = (
            self.record(27)
        )
        self.worker.sensor_repository.insert.return_value = True
        self.assertEqual(
            self.worker.reprocess_rejections(refresh_from_firebase=True),
            (1, 1, 0, 0),
        )
        self.worker.firebase.sensor_data.assert_called_once_with("EST_TEST")
        self.worker.firebase.sensor_data.return_value.child.assert_called_once_with("-001")
        obj = self.worker.sensor_repository.insert.call_args.args[0]
        self.assertEqual(obj.temperatura, 27)
        self.assertEqual(rejected.payload, self.record("inválido"))

    def test_reprocess_invalid_payload_remains_pending_with_new_reason(self):
        rejected = self.rejection(self.record("inválido"))
        self.worker.rejections.pending.return_value = [rejected]
        self.assertEqual(self.worker.reprocess_rejections(), (1, 0, 0, 1))
        self.worker.rejections.mark_resolved.assert_not_called()
        self.worker.sensor_repository.insert.assert_not_called()
        args = self.worker.rejections.mark_failed.call_args.args
        self.assertIs(args[0], rejected)
        self.assertIn("ValueError", args[1])

    def test_reprocess_missing_firebase_record_keeps_original_pending(self):
        rejected = self.rejection()
        self.worker.rejections.pending.return_value = [rejected]
        self.worker.firebase.sensor_data.return_value.child.return_value.get.return_value = None
        self.assertEqual(
            self.worker.reprocess_rejections(refresh_from_firebase=True),
            (1, 0, 0, 1),
        )
        self.worker.rejections.mark_failed.assert_called_once()
        self.worker.rejections.mark_resolved.assert_not_called()

    def test_reprocess_firebase_read_failure_remains_pending(self):
        self.worker.rejections.pending.return_value = [self.rejection()]
        self.worker.firebase.sensor_data.return_value.child.return_value.get.side_effect = (
            RuntimeError("rede")
        )
        self.assertEqual(
            self.worker.reprocess_rejections(refresh_from_firebase=True),
            (1, 0, 0, 1),
        )
        self.worker.rejections.mark_failed.assert_called_once()
        self.worker.rejections.mark_resolved.assert_not_called()
        self.worker.sensor_repository.insert.assert_not_called()

    def test_reprocess_continues_after_a_record_error(self):
        rejected = self.rejection(self.record("inválido"))
        valid = self.rejection()
        valid.firebase_id = "-002"
        self.worker.rejections.pending.return_value = [rejected, valid]
        self.worker.sensor_repository.insert.return_value = True
        self.assertEqual(self.worker.reprocess_rejections(), (2, 1, 0, 1))
        self.worker.rejections.mark_failed.assert_called_once()
        self.worker.rejections.mark_resolved.assert_called_once_with(valid)

    def test_reprocess_database_failure_does_not_resolve(self):
        self.worker.rejections.pending.return_value = [self.rejection()]
        self.worker.sensor_repository.insert.side_effect = RuntimeError("DB")
        self.assertEqual(self.worker.reprocess_rejections(), (1, 0, 0, 1))
        self.worker.rejections.mark_failed.assert_called_once()
        self.worker.rejections.mark_resolved.assert_not_called()

    def test_reprocess_existing_record_is_resolved_idempotently(self):
        self.worker.rejections.pending.return_value = [self.rejection()]
        self.worker.sensor_repository.insert.return_value = False
        self.assertEqual(self.worker.reprocess_rejections(), (1, 0, 1, 0))
        self.worker.rejections.mark_resolved.assert_called_once()

    def test_reprocess_resolution_failure_aborts_for_safe_replay(self):
        self.worker.rejections.pending.return_value = [self.rejection()]
        self.worker.sensor_repository.insert.return_value = True
        self.worker.rejections.mark_resolved.side_effect = RuntimeError("resolve")
        with self.assertRaisesRegex(RuntimeError, "resolve"):
            self.worker.reprocess_rejections()
        self.worker.sensor_repository.insert.assert_called_once()
        self.worker.rejections.mark_failed.assert_not_called()

    def test_reprocess_attempt_recording_failure_is_not_hidden(self):
        self.worker.rejections.pending.return_value = [
            self.rejection(self.record("inválido")),
        ]
        self.worker.rejections.mark_failed.side_effect = RuntimeError("attempt")
        with self.assertRaisesRegex(RuntimeError, "attempt"):
            self.worker.reprocess_rejections()

    def test_reprocess_buoy_routes_to_buoy_repository(self):
        rejected = Rejection(
            "boias", "BOIA_TEST", "-001",
            {"hora": "2026-08-20 17:29:06", "ph": 7}, "Erro anterior",
        )
        self.worker.rejections.pending.return_value = [rejected]
        self.worker.buoy_repository = Mock()
        self.worker.buoy_repository.insert.return_value = True
        self.assertEqual(self.worker.reprocess_rejections(), (1, 1, 0, 0))
        self.assertEqual(
            self.worker.buoy_repository.insert.call_args.args[0].buoy_id,
            "BOIA_TEST",
        )
        self.worker.sensor_repository.insert.assert_not_called()

    def test_reprocess_empty_batch(self):
        self.worker.rejections.pending.return_value = []
        self.assertEqual(self.worker.reprocess_rejections(), (0, 0, 0, 0))
        self.worker.rejections.mark_resolved.assert_not_called()

    def test_buoy_rejections_use_buoy_source_and_block_checkpoint_on_failure(self):
        self.worker.firebase.buoys.return_value.get.return_value = {"BOIA_TEST": True}
        query = self.worker.firebase.buoy_data.return_value.order_by_key.return_value
        query.get.return_value = {"-001": {"hora": "inválido", "ph": 7}}
        self.worker.rejections.save_many.side_effect = RuntimeError("DB")
        self.assertEqual(self.worker.process_buoys(), (1, 0, 0, 1))
        rejected = self.worker.rejections.save_many.call_args.args[0][0]
        self.assertEqual((rejected.source, rejected.device_id), ("boias", "BOIA_TEST"))
        self.worker.checkpoints.set.assert_not_called()
