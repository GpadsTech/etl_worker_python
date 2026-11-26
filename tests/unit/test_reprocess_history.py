"""Validação do comando histórico antes de abrir conexões."""

import unittest
from unittest.mock import patch

from app.reprocess_history import main


class TestHistoryCLI(unittest.TestCase):
    def test_invalid_arguments_never_create_worker(self):
        cases = [
            ["backfill", "--source", "boias", "--device-id", "B"],
            ["correct", "--source", "boias", "--device-id", "B", "--key", "K"],
            ["correct", "--source", "boias", "--device-id", "B",
             "--key", "K", "--reason", "R", "--apply", "--expected-hash", "H"],
        ]
        for args in cases:
            with patch("app.reprocess_history.ETLWorker") as worker, \
                    patch("sys.stderr"), self.assertRaises(SystemExit) as exit:
                main(args)
            self.assertEqual(exit.exception.code, 2)
            worker.assert_not_called()

    def test_operational_error_returns_failure_without_logging_payload(self):
        with patch("app.reprocess_history.ETLWorker") as worker, \
                patch("app.reprocess_history.backfill", side_effect=RuntimeError("private payload")):
            result = main(["backfill", "--source", "boias", "--device-id", "B",
                           "--start", "K1", "--end", "K2"])
        self.assertEqual(result, 1)
        self.assertNotIn("private payload", str(worker.return_value.logger.mock_calls))
        worker.return_value.database.close.assert_called_once()
