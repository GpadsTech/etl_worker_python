"""Trava em duas sessões PostgreSQL; sem Firebase nem tabelas permanentes."""

import secrets
from unittest.mock import patch

from app.database.connection import WorkerAlreadyRunningError, WorkerLockLostError
from tests.integration.gate import integration_test
from tests.integration.temporary_database import TemporaryDatabase, TemporaryDatabaseTestCase


@integration_test
class TestWorkerLock(TemporaryDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.other = TemporaryDatabase()
        self.addCleanup(self.other.close)
        self.other.connect()
        # Isolar estes testes de qualquer chave de aplicação em uso no banco.
        key_patch = patch(
            "app.database.connection.ETL_LOCK_KEY", secrets.randbits(63),
        )
        key_patch.start()
        self.addCleanup(key_patch.stop)

    def test_second_session_is_denied_until_first_releases(self):
        with self.database.exclusive():
            self.database.commit()
            self.database.rollback()
            with self.assertRaises(WorkerAlreadyRunningError):
                with self.other.exclusive():
                    self.fail("Duas sessões não podem executar juntas.")
        with self.other.exclusive():
            with self.assertRaises(WorkerAlreadyRunningError):
                with self.database.exclusive():
                    self.fail("Segunda sessão deve continuar exclusiva.")

    def test_body_exception_does_not_leave_lock_behind(self):
        with self.assertRaises(ValueError):
            with self.database.exclusive():
                raise ValueError("falha de teste")
        with self.other.exclusive():
            pass

    def test_session_close_releases_lock_but_old_operation_cannot_resume(self):
        with self.assertRaises(WorkerLockLostError):
            with self.database.exclusive():
                self.database.close()
                with self.other.exclusive():
                    pass
                self.database.commit()
