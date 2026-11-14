"""Isolamento SQL por sessão, sem gravar nem apagar tabelas permanentes.

As tabelas temporárias preservam linhas entre commits e são descartadas pelo
PostgreSQL ao fechar a conexão. Não substituem testes específicos de TimescaleDB.
"""

import unittest

from app.database.connection import DatabaseConnection
from app.repository.sensor_repository import SensorRepository
from app.repository.buoy_repository import BuoyRepository


class TemporaryDatabase(DatabaseConnection):
    """Conexão exclusiva de teste; nunca reconecta após perder suas tabelas TEMP."""

    def __init__(self):
        super().__init__()
        self._prepared = False

    def connect(self):
        if self._prepared:
            if self.connection is None or self.connection.closed:
                raise ConnectionError(
                    "Conexão temporária encerrada; não é seguro reconectar."
                )
            return self.connection

        connection = super().connect()
        try:
            with connection.cursor() as cursor:
                # Mesmo se uma tabela TEMP faltar, não procurar em public.
                cursor.execute("SET search_path TO pg_temp, pg_catalog;")
                for repository, device_column in (
                    (SensorRepository, "sensor_id"),
                    (BuoyRepository, "buoy_id"),
                ):
                    numeric_columns = ", ".join(
                        f"{column} DOUBLE PRECISION"
                        for column in repository.columns[3:]
                    )
                    cursor.execute(f"""
                        CREATE TEMP TABLE {repository.table_name} (
                            firebase_id TEXT NOT NULL,
                            {device_column} TEXT NOT NULL,
                            timestamp TIMESTAMP NOT NULL,
                            {numeric_columns},
                            PRIMARY KEY (firebase_id, timestamp)
                        ) ON COMMIT PRESERVE ROWS;
                    """)
                cursor.execute("""
                    CREATE TEMP TABLE etl_checkpoint (
                        source TEXT NOT NULL,
                        device_id TEXT NOT NULL,
                        last_key TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (source, device_id)
                    ) ON COMMIT PRESERVE ROWS;
                """)
            self.commit()
        except Exception:
            self.close()
            raise
        self._prepared = True
        return connection


class TemporaryDatabaseTestCase(unittest.TestCase):
    """Registra a limpeza antes da preparação, inclusive para falhas no setUp."""

    def setUp(self):
        super().setUp()
        self.database = TemporaryDatabase()
        self.addCleanup(self.database.close)
        self.database.connect()
