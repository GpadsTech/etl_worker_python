"""Interface de reprocessamento, códigos de saída e fechamento da conexão."""

import unittest
from unittest.mock import Mock, patch

from app.reprocess_rejections import main
from app.database.connection import WorkerAlreadyRunningError


class TestReprocessRejections(unittest.TestCase):
    def setUp(self):
        self.worker = Mock()
        self.worker.reprocess_rejections.return_value = (1, 1, 0, 0)
        self.worker_patch = patch(
            "app.reprocess_rejections.ETLWorker", return_value=self.worker,
        )
        self.factory = self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)
        logger_patch = patch("app.reprocess_rejections.get_logger")
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    def test_defaults_and_success_close_connection(self):
        self.assertEqual(main([]), 0)
        self.worker.reprocess_rejections.assert_called_once_with(
            limit=100, source=None, device_id=None, refresh_from_firebase=False,
        )
        self.worker.database.close.assert_called_once()

    def test_filters_and_refresh_are_forwarded(self):
        self.assertEqual(main([
            "--limit", "5", "--source", "boias", "--device-id", "BOIA_TEST",
            "--refresh-from-firebase",
        ]), 0)
        self.worker.reprocess_rejections.assert_called_once_with(
            limit=5, source="boias", device_id="BOIA_TEST", refresh_from_firebase=True,
        )

    def test_partial_failure_exits_nonzero_and_closes(self):
        self.worker.reprocess_rejections.return_value = (2, 1, 0, 1)
        self.assertEqual(main([]), 1)
        self.worker.database.close.assert_called_once()

    def test_operational_failure_exits_nonzero_and_closes(self):
        self.worker.reprocess_rejections.side_effect = RuntimeError("DB")
        self.assertEqual(main([]), 1)
        self.worker.database.close.assert_called_once()

    def test_busy_worker_exits_nonzero_and_closes(self):
        self.worker.reprocess_rejections.side_effect = WorkerAlreadyRunningError()
        self.assertEqual(main([]), 1)
        self.worker.database.close.assert_called_once()

    def test_invalid_arguments_fail_before_constructing_worker(self):
        for args in (["--limit", "0"], ["--limit", "-1"], ["--source", "outra"]):
            with self.subTest(args=args), patch("sys.stderr"):
                with self.assertRaises(SystemExit) as result:
                    main(args)
                self.assertEqual(result.exception.code, 2)
        self.factory.assert_not_called()
