"""
Gerencia a conexão com o PostgreSQL / TimescaleDB.
"""

import psycopg2
from psycopg2.extensions import connection

from app.config.config import config


class DatabaseConnection:
    """
    Gerencia a conexão com o PostgreSQL/TimescaleDB.
    """

    def __init__(self) -> None:
        self.connection: connection | None = None

    def connect(self) -> connection:
        """
        Abre uma conexão com o banco de dados.

        Returns:
            connection: conexão ativa com o PostgreSQL.
        """

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

        if self.connection:
            self.connection.commit()

    def rollback(self) -> None:
        """
        Desfaz a transação atual.
        """

        if self.connection:
            self.connection.rollback()

    def close(self) -> None:
        """
        Fecha a conexão com o banco.
        """

        if self.connection and not self.connection.closed:
            self.connection.close()