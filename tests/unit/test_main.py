"""Comportamento do supervisor quando outro worker já possui a trava."""

import unittest
from unittest.mock import Mock, patch

from app.main import main
from app.database.connection import WorkerAlreadyRunningError, WorkerLockLostError


class TestMain(unittest.TestCase):
    def setUp(self):
        self.worker = Mock()
        factory_patch = patch("app.main.ETLWorker", return_value=self.worker)
        factory_patch.start()
        self.addCleanup(factory_patch.stop)
        logger_patch = patch("app.main.get_logger")
        self.logger = logger_patch.start().return_value
        self.addCleanup(logger_patch.stop)
        sleep_patch = patch("app.main.time.sleep", side_effect=KeyboardInterrupt)
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def test_busy_cycle_waits_instead_of_spinning_or_reporting_ingestion_success(self):
        self.worker.run_once.side_effect = WorkerAlreadyRunningError()
        main()
        self.worker.run_once.assert_called_once()
        self.sleep.assert_called_once()
        self.logger.exception.assert_not_called()
        messages = str(self.logger.info.call_args_list)
        self.assertIn("este ciclo não será executado", messages)
        self.assertNotIn("Ciclo concluído", messages)
        self.worker.database.close.assert_called_once()

    def test_lost_session_finishes_cycle_and_only_then_attempts_a_new_cycle(self):
        self.worker.run_once.side_effect = [
            WorkerLockLostError(), ((0, 0, 0, 0), (0, 0, 0, 0)),
        ]
        self.sleep.side_effect = [None, KeyboardInterrupt]
        main()
        self.assertEqual(self.worker.run_once.call_count, 2)
        self.assertEqual(self.sleep.call_count, 2)
        self.logger.exception.assert_called_once()
        self.worker.database.close.assert_called_once()
