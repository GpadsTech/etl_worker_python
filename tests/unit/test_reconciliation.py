"""Reconciliação determinística, sem Firebase/PostgreSQL reais."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.operations.backup import file_hash, fingerprints, restore_empty_local
from app.operations.reconcile import (
    compare, digest, expected_rows, select_scope, snapshot_delta, write_daily_csv,
)
from app.operations.rehearse import Query, SnapshotSource


class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "sensores": {"EST": {"a": {"hora": "2026-08-20 23:30:00", "temperatura": "21"}}},
            "boias": {"BOIA": {
                "a": {"hora": "2026-08-20 23:30:00", "ph": "7"},
                "b": {"hora": "2026-08-20 23:30:00", "ph": "8"},
            }},
        }
        rows, checkpoints, _ = expected_rows(self.snapshot)
        self.actual = dict(rows, etl_rejections=[], etl_checkpoint=[
            dict(row, updated_at="2026-08-21T04:00:00+00:00") for row in checkpoints
        ])

    def report(self):
        return compare(self.snapshot, self.actual)

    def test_complete_match_checks_all_values_and_checkpoints(self):
        report = self.report()
        self.assertTrue(report["passed"])
        self.assertEqual(report["unexplained_differences"], 0)
        device = report["tables"]["buoy_data"]["actual"]["devices"]["BOIA"]
        self.assertEqual(device["by_day_America_Sao_Paulo"], {"2026-08-20": 2})
        self.assertEqual(device["min_utc"], "2026-08-21T02:30:00+00:00")
        self.assertEqual(device["nulls"]["adc"], 2)

    def test_equal_counts_do_not_hide_missing_and_extra_keys(self):
        self.actual["buoy_data"][0]["firebase_id"] = "different"
        report = self.report()
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["tables"]["buoy_data"]["missing"]), 1)
        self.assertEqual(len(report["tables"]["buoy_data"]["extra"]), 1)

    def test_changed_measurement_is_reported_by_field(self):
        self.actual["buoy_data"][0]["ph"] = 22.84
        report = self.report()
        self.assertFalse(report["passed"])
        self.assertEqual(report["tables"]["buoy_data"]["changed"][0]["fields"], ["ph"])

    def test_missing_nullable_column_is_reported_not_confused_with_null(self):
        del self.actual["sensor_data"][0]["chuva"]
        report = self.report()
        self.assertFalse(report["passed"])
        self.assertIn("chuva", report["tables"]["sensor_data"]["changed"][0]["fields"])

    def test_duplicate_target_keys_are_not_hidden_by_mapping(self):
        self.actual["sensor_data"].append(deepcopy(self.actual["sensor_data"][0]))
        self.assertFalse(self.report()["passed"])
        self.assertEqual(self.report()["tables"]["sensor_data"]["duplicate_keys"], 1)

    def test_stale_checkpoint_is_a_difference(self):
        self.actual["etl_checkpoint"][0]["last_key"] = "old"
        self.assertFalse(self.report()["passed"])

    def test_invalid_source_is_not_silently_dropped(self):
        self.snapshot["boias"]["BOIA"]["invalid"] = None
        self.assertFalse(self.report()["passed"])
        self.assertEqual(len(self.report()["invalid_source"]), 1)

    def test_unexplained_pending_rejection_fails(self):
        self.actual["etl_rejections"] = [{
            "source": "boias", "device_id": "BOIA", "firebase_id": "unknown",
            "payload": {}, "reason": "bad", "attempts": 1,
            "created_at": "2026-08-21T04:00:00+00:00",
            "last_attempt_at": "2026-08-21T04:00:00+00:00", "resolved_at": None,
        }]
        self.assertFalse(self.report()["passed"])

    def test_small_scope_is_explicit_and_limits_each_device(self):
        report = compare(self.snapshot, self.actual, 1)
        self.assertTrue(report["passed"])
        self.assertEqual(report["tables"]["buoy_data"]["actual"]["count"], 1)
        with self.assertRaises(ValueError):
            select_scope(self.snapshot, 0)

    def test_equivalent_offsets_compare_as_same_instant(self):
        self.actual["sensor_data"][0]["timestamp"] = "2026-08-20T23:30:00-03:00"
        self.assertTrue(self.report()["passed"])

    def test_digest_rejects_naive_datetime_and_nonfinite_numbers(self):
        with self.assertRaises(ValueError):
            digest(datetime(2026, 8, 20))
        with self.assertRaises(ValueError):
            digest(float("nan"))
        self.assertEqual(
            digest(datetime(2026, 8, 20, tzinfo=timezone.utc)),
            digest("2026-08-20T00:00:00+00:00"),
        )

    def test_table_fingerprints_do_not_depend_on_row_order(self):
        self.assertEqual(
            fingerprints({"table": [{"id": 2}, {"id": 1}]}),
            fingerprints({"table": [{"id": 1}, {"id": 2}]}),
        )

    def test_snapshot_query_preserves_inclusive_checkpoint_boundary(self):
        query = Query({"c": 3, "a": 1, "b": 2})
        self.assertEqual(query.order_by_key().start_at("b").get(), {"b": 2, "c": 3})
        self.assertEqual(query.get(shallow=True), {"a": True, "b": True, "c": True})
        source = SnapshotSource(self.snapshot)
        self.assertEqual(source.sensors().get(shallow=True), {"EST": True})
        self.assertFalse(hasattr(source, "set"))

    def test_restore_refuses_remote_host_before_reading_archive(self):
        with patch("app.operations.backup.config") as config:
            config.POSTGRES_HOST = "database.example"
            with self.assertRaises(ValueError):
                restore_empty_local("nonexistent", confirmed=True)

    def test_restore_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            restore_empty_local("nonexistent")

    def test_delta_distinguishes_new_late_changed_and_removed_records(self):
        after = deepcopy(self.snapshot)
        del after["boias"]["BOIA"]["a"]
        after["boias"]["BOIA"]["0"] = {"hora": "2026-08-20 23:30:00"}
        after["boias"]["BOIA"]["b"]["ph"] = "9"
        result = snapshot_delta(self.snapshot, after)
        self.assertEqual(
            [result[name] for name in (
                "added_count", "removed_count", "changed_count", "late_added_count",
            )], [1, 1, 1, 1],
        )

    def test_daily_csv_uses_local_day_and_records_zero_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "daily.csv"
            write_daily_csv(path, self.report())
            self.assertIn("2026-08-20,2,2,0", path.read_text())

    def test_nonempty_restore_target_is_refused_before_running_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "data.dump"
            archive.write_bytes(b"test-only")
            (Path(directory) / "manifest.json").write_text(json.dumps({
                "kind": "data_only", "schema": "etl_private",
                "archive_sha256": file_hash(archive), "migrations": {},
            }))
            with patch("app.operations.backup.config") as config:
                config.POSTGRES_HOST = "127.0.0.1"
                config.POSTGRES_SCHEMA = "etl_private"
                with patch("app.operations.backup.DatabaseConnection", return_value=MagicMock()):
                    with patch("app.operations.backup.read_tables", return_value={"table": [{"id": 1}]}):
                        with patch("app.operations.backup.postgres_tool") as tool:
                            with self.assertRaisesRegex(ValueError, "Destino não vazio"):
                                restore_empty_local(directory, confirmed=True)
                            tool.assert_not_called()

    def test_corrupted_backup_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "data.dump").write_bytes(b"modified")
            (Path(directory) / "manifest.json").write_text(json.dumps({
                "kind": "data_only", "schema": "etl_private", "archive_sha256": "incorrect",
            }))
            with patch("app.operations.backup.config") as config:
                config.POSTGRES_HOST = "127.0.0.1"
                config.POSTGRES_SCHEMA = "etl_private"
                with self.assertRaisesRegex(ValueError, "Checksum"):
                    restore_empty_local(directory, confirmed=True)
