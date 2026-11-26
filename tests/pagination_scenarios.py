"""Cenários reutilizados com armazenamento em memória e SQL TEMP real."""

from unittest.mock import patch

from app.operations.rehearse import SnapshotSource
from app.reprocess_history import backfill
from tests.unit.test_pagination import key


def record(value=25):
    return {"hora": "2026-08-20 17:29:06", "temperatura": value}


class PaginationScenarios:
    def prepare_source(self):
        self.records = {key(n): record(n) for n in (5, 1, 4, 2, 3)}
        self.source = SnapshotSource({"sensores": {"EST": self.records}, "boias": {}})
        worker = self.new_worker()
        worker.firebase = self.source
        worker.page_size = 2
        worker.lookback_records = 3
        return worker

    def restart(self):
        worker = self.new_worker()
        worker.firebase = self.source
        worker.page_size = 2
        worker.lookback_records = 3
        return worker

    def test_bootstrap_and_repeated_cycle_have_no_duplicates(self):
        worker = self.prepare_source()
        self.assertEqual(worker.process_sensors(), (5, 5, 0, 0))
        self.assertEqual(worker.checkpoints.get("sensores", "EST"), key(5))
        self.assertEqual(self.restart().process_sensors(), (0, 0, 0, 0))
        self.assertEqual(self.count(), 5)

    def test_interruption_after_commit_before_checkpoint_replays_safely(self):
        worker = self.prepare_source()
        with patch.object(worker.checkpoints, "set", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                worker.process_sensors()
        self.assertEqual(self.count(), 2)
        self.assertIsNone(worker.checkpoints.get("sensores", "EST"))
        self.assertEqual(self.restart().process_sensors(), (5, 3, 2, 0))
        self.assertEqual(self.count(), 5)

    def test_checkpoint_failure_stops_before_next_page(self):
        worker = self.prepare_source()
        with patch.object(worker.checkpoints, "set", side_effect=RuntimeError):
            worker.process_sensors()
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.restart().process_sensors(), (5, 3, 2, 0))

    def test_repeated_source_page_stops_and_restart_loses_nothing(self):
        from app.firebase.pagination import read_result
        worker = self.prepare_source()
        calls = 0

        def repeated(query, limit):
            nonlocal calls
            calls += 1
            if calls == 3:
                return {key(1): record(1), key(2): record(2)}
            return read_result(query, limit)

        with patch("app.firebase.pagination.read_result", side_effect=repeated):
            with self.assertRaises(RuntimeError):
                worker.process_sensors()
        self.assertEqual(worker.checkpoints.get("sensores", "EST"), key(2))
        self.assertEqual(self.count(), 2)
        self.restart().process_sensors()
        self.assertEqual(self.count(), 5)

    def test_new_tail_during_cycle_waits_for_next_cycle(self):
        worker = self.prepare_source()
        insert = worker.sensor_repository.insert_many

        def append_tail(objects):
            self.records[key(6)] = record(6)
            return insert(objects)

        with patch.object(worker.sensor_repository, "insert_many", side_effect=append_tail):
            self.assertEqual(worker.process_sensors(), (5, 5, 0, 0))
        self.assertEqual(worker.checkpoints.get("sensores", "EST"), key(5))
        self.assertEqual(self.restart().process_sensors(), (1, 1, 0, 0))

    def test_second_page_database_failure_keeps_first_page_cursor(self):
        worker = self.prepare_source()
        insert = worker.sensor_repository.insert_many
        calls = 0

        def fail_second(objects):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("controlled failure")
            return insert(objects)

        with patch.object(worker.sensor_repository, "insert_many", side_effect=fail_second):
            worker.process_sensors()
        self.assertEqual(worker.checkpoints.get("sensores", "EST"), key(2))
        self.assertEqual(self.count(), 2)
        self.restart().process_sensors()
        self.assertEqual(self.count(), 5)

    def test_rejection_failure_blocks_page_checkpoint_then_restart(self):
        worker = self.prepare_source()
        self.records[key(2)] = None
        with patch.object(worker.rejections, "save_many", side_effect=RuntimeError):
            worker.process_sensors()
        self.assertIsNone(worker.checkpoints.get("sensores", "EST"))
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.restart().process_sensors(), (5, 3, 1, 1))
        self.assertEqual(len(worker.rejections.pending()), 1)
        self.assertEqual(worker.checkpoints.get("sensores", "EST"), key(5))

    def test_interruption_after_rejection_commit_is_duplicate_safe(self):
        worker = self.prepare_source()
        self.records[key(2)] = None
        with patch.object(worker.checkpoints, "set", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                worker.process_sensors()
        self.assertEqual(len(worker.rejections.pending()), 1)
        self.restart().process_sensors()
        self.assertEqual(self.count(), 4)
        self.assertEqual(len(worker.rejections.pending()), 1)

    def test_late_records_inside_window_recovered_outside_require_backfill(self):
        worker = self.prepare_source()
        del self.records[key(2)]
        del self.records[key(4)]
        worker.process_sensors()
        self.records[key(4)] = record(44)
        self.records[key(0)] = record(0)
        self.assertEqual(self.restart().process_sensors(), (1, 1, 0, 0))
        self.assertEqual(self.count(), 4)
        before = worker.checkpoints.get("sensores", "EST")
        self.assertEqual(backfill(worker, "sensores", "EST", key(0), key(5)), (1, 1, 0, 0))
        self.assertEqual(worker.checkpoints.get("sensores", "EST"), before)
        self.assertEqual(self.count(), 5)
        self.assertEqual(backfill(worker, "sensores", "EST", key(0), key(5)), (0, 0, 0, 0))

    def test_lookback_does_not_reopen_known_rejections(self):
        worker = self.prepare_source()
        self.records[key(4)] = None
        worker.process_sensors()
        self.records[key(4)] = record(40)
        self.assertEqual(self.restart().process_sensors(), (0, 0, 0, 0))
        self.assertEqual(len(worker.rejections.pending()), 1)
        self.assertEqual(self.count(), 4)

    def test_disabled_window_only_reads_forward(self):
        worker = self.prepare_source()
        del self.records[key(4)]
        worker.process_sensors()
        self.records[key(4)] = record(44)
        self.records[key(6)] = record(6)
        worker.lookback_records = 0
        self.assertEqual(worker.process_sensors(), (1, 1, 0, 0))
        self.assertEqual(self.count(), 5)

    def test_backfill_stops_on_failure_without_advancing_checkpoint(self):
        worker = self.prepare_source()
        with patch.object(worker.sensor_repository, "insert_many", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                backfill(worker, "sensores", "EST", key(1), key(5))
        self.assertIsNone(worker.checkpoints.get("sensores", "EST"))
        self.assertEqual(self.count(), 0)
