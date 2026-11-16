"""
Gerencia a conexão com o PostgreSQL / TimescaleDB.
"""

from contextlib import contextmanager

import psycopg2
from psycopg2.extensions import connection

from app.config.config import config


# Chave bigint estável, compartilhada por ingestão e reprocessamento no banco.
ETL_LOCK_KEY = int.from_bytes(b"MORHINGA", "big")


class WorkerAlreadyRunningError(RuntimeError):
    """Outra sessão já possui a exclusividade do ETL."""


class WorkerLockLostError(ConnectionError):
    """A sessão protegida foi perdida; é proibido reconectar neste trabalho."""


class DatabaseConnection:
    """
    Gerencia a conexão com o PostgreSQL/TimescaleDB.
    """

    def __init__(self) -> None:
        self.connection: connection | None = None
        self._lock_connection: connection | None = None
        self._exclusive_depth = 0

    def _check_lock_session(self) -> None:
        if self._exclusive_depth and (
            self.connection is not self._lock_connection
            or self._lock_connection.closed
        ):
            raise WorkerLockLostError(
                "Sessão da trava perdida; interrompa a operação antes de reconectar."
            )

    @contextmanager
    def exclusive(self):
        """Trava de sessão para uma operação inteira, com aninhamento local.

        Exige conexão direta ou pooler em modo session, nunca transaction.
        Commits/rollbacks não liberam a trava. Todos os repositórios devem
        usar esta mesma DatabaseConnection; não se reconecta dentro do bloco.
        """
        if self._exclusive_depth:
            self._check_lock_session()
            self._exclusive_depth += 1
            try:
                yield
            finally:
                self._exclusive_depth -= 1
            return

        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s);", (ETL_LOCK_KEY,))
                acquired = cursor.fetchone()[0]
            # Não deixar uma transação ociosa durante chamadas ao Firebase.
            connection.commit()
        except BaseException:
            # A aquisição pode ter ocorrido antes da falha do commit.
            self.close()
            raise

        if not acquired:
            raise WorkerAlreadyRunningError("Outro processo já está executando o ETL.")

        self._lock_connection = connection
        self._exclusive_depth = 1
        try:
            yield
        finally:
            try:
                self._check_lock_session()
                # Limpa leituras ou transações abortadas antes de liberar.
                connection.rollback()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s);", (ETL_LOCK_KEY,))
                    released = cursor.fetchone()[0]
                connection.commit()
                if not released:
                    raise WorkerLockLostError("A sessão não possuía mais a trava do ETL.")
            except BaseException:
                # Fechar a sessão original garante a liberação mesmo se o
                # unlock falhar; nunca liberar por uma conexão substituta.
                connection.close()
                if self.connection is not connection:
                    self.close()
                raise
            finally:
                self._exclusive_depth = 0
                self._lock_connection = None

    def connect(self) -> connection:
        """
        Abre uma conexão com o banco de dados.

        Returns:
            connection: conexão ativa com o PostgreSQL.
        """

        self._check_lock_session()

        if self.connection is None or self.connection.closed:

            self.connection = psycopg2.connect(
                host=config.POSTGRES_HOST,
                port=config.POSTGRES_PORT,
                dbname=config.POSTGRES_DB,
                user=config.POSTGRES_USER,
                password=config.POSTGRES_PASSWORD,
            )

        return self.connection

    def commit(self) -> None:
        """
        Confirma a transação atual.
        """

        self._check_lock_session()
        if self.connection:
            self.connection.commit()

    def rollback(self) -> None:
        """
        Desfaz a transação atual.
        """

        self._check_lock_session()
        if self.connection:
            self.connection.rollback()

    def close(self) -> None:
        """
        Fecha a conexão com o banco.
        """

        if self.connection and not self.connection.closed:
            self.connection.close()
