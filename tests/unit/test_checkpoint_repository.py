"""Leitura/escrita do checkpoint com conexão simulada."""

import unittest
from unittest.mock import MagicMock

from app.repository.checkpoint_repository import CheckpointRepository


class TestCheckpointRepository(unittest.TestCase):
    def setUp(self):
        self.database = MagicMock()
        self.cursor = (
            self.database.connect.return_value.cursor.return_value.__enter__.return_value
        )
        self.repository = CheckpointRepository(self.database)

    def test_missing_checkpoint_returns_none(self):
        self.cursor.fetchone.return_value = None
        self.assertIsNone(self.repository.get("sensores", "EST_TEST"))

    def test_read_checkpoint_uses_source_and_device(self):
        self.cursor.fetchone.return_value = ("-001",)
        self.assertEqual(self.repository.get("sensores", "EST_TEST"), "-001")
        self.assertEqual(
            self.cursor.execute.call_args.args[1], ("sensores", "EST_TEST"),
        )

    def test_set_commits_upsert(self):
        self.repository.set("boias", "BOIA_TEST", "-002")
        sql, params = self.cursor.execute.call_args.args
        self.assertIn("ON CONFLICT (source, device_id)", sql)
        self.assertEqual(params, ("boias", "BOIA_TEST", "-002"))
        self.database.commit.assert_called_once()
        self.database.rollback.assert_not_called()

    def test_failed_set_rolls_back_and_propagates(self):
        self.cursor.execute.side_effect = RuntimeError("DB")
        with self.assertRaisesRegex(RuntimeError, "DB"):
            self.repository.set("boias", "BOIA_TEST", "-002")
        self.database.rollback.assert_called_once()
        self.database.commit.assert_not_called()
