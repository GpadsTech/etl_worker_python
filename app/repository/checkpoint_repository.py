"""
Repository do checkpoint de leitura incremental.

Guarda, por origem (``sensores``/``boias``) e por equipamento, a última
chave do Firebase já processada (medição ou rejeição persistida).
A próxima leitura começa nessa chave e
pula o próprio registro de fronteira (``start_at`` é inclusivo).
"""

from app.database.connection import DatabaseConnection


class CheckpointRepository:

    def __init__(self, database: DatabaseConnection):
        self.database = database

    def get(self, source: str, device_id: str) -> str | None:
        """
        Retorna a última chave processada ou ``None`` se não houver.
        """

        connection = self.database.connect()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT last_key
                FROM etl_checkpoint
                WHERE source = %s AND device_id = %s;
                """,
                (source, device_id),
            )

            row = cursor.fetchone()

        return row[0] if row else None

    def set(self, source: str, device_id: str, last_key: str) -> None:
        """
        Grava a última chave processada.

        Deve ser chamado somente depois dos commits dos dados e das
        rejeições. O upsert mantém uma linha por (origem, equipamento).
        """

        connection = self.database.connect()

        try:

            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    INSERT INTO etl_checkpoint (
                        source,
                        device_id,
                        last_key,
                        updated_at
                    )
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (source, device_id)
                    DO UPDATE SET
                        last_key = EXCLUDED.last_key,
                        updated_at = now();
                    """,
                    (source, device_id, last_key),
                )

            self.database.commit()

        except Exception:

            self.database.rollback()

            raise
