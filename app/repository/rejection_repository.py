"""Persistência durável de rejeições, independente do checkpoint."""

from psycopg2.extras import Json, execute_values

from app.database.connection import DatabaseConnection
from app.models.rejection import Rejection
from app.repository.base import BATCH_SIZE


class RejectionRepository:
    def __init__(self, database: DatabaseConnection):
        self.database = database

    def save_many(self, rejections) -> None:
        """Commit de todas as rejeições ou rollback; replay não cria duplicatas."""
        rejections = list(rejections)
        if not rejections:
            return

        connection = self.database.connect()
        try:
            with connection.cursor() as cursor:
                for start in range(0, len(rejections), BATCH_SIZE):
                    chunk = rejections[start:start + BATCH_SIZE]
                    execute_values(
                        cursor,
                        """
                        INSERT INTO etl_rejections (
                            source, device_id, firebase_id, payload, reason
                        ) VALUES %s
                        ON CONFLICT (source, device_id, firebase_id)
                        DO UPDATE SET
                            payload = EXCLUDED.payload,
                            reason = EXCLUDED.reason,
                            attempts = etl_rejections.attempts + 1,
                            last_attempt_at = now(),
                            resolved_at = NULL;
                        """,
                        [
                            (
                                item.source, item.device_id, item.firebase_id,
                                Json(item.payload), item.reason,
                            )
                            for item in chunk
                        ],
                        page_size=len(chunk),
                    )
            self.database.commit()
        except Exception:
            self.database.rollback()
            raise

    def pending(
        self,
        limit: int = 100,
        source: str | None = None,
        device_id: str | None = None,
    ) -> list[Rejection]:
        """Um lote finito; tentativas mais antigas primeiro, sem alterar status."""
        if limit <= 0:
            raise ValueError("O limite deve ser positivo.")
        if source is not None and source not in ("sensores", "boias"):
            raise ValueError("Origem inválida.")

        connection = self.database.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT source, device_id, firebase_id, payload, reason
                    FROM etl_rejections
                    WHERE resolved_at IS NULL
                      AND (%s IS NULL OR source = %s)
                      AND (%s IS NULL OR device_id = %s)
                    ORDER BY last_attempt_at, source, device_id, firebase_id
                    LIMIT %s;
                    """,
                    (source, source, device_id, device_id, limit),
                )
                return [Rejection(*row) for row in cursor.fetchall()]
        except Exception:
            self.database.rollback()
            raise

    def mark_resolved(self, rejection: Rejection) -> None:
        """Chamar somente após o commit da medição, inclusive em replay."""
        self._record_attempt(rejection, None)

    def mark_failed(self, rejection: Rejection, reason: str) -> None:
        """Preserva o payload salvo e mantém a leitura disponível para retry."""
        self._record_attempt(rejection, reason)

    def _record_attempt(self, rejection: Rejection, reason: str | None) -> None:
        connection = self.database.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE etl_rejections
                    SET reason = COALESCE(%s, reason),
                        attempts = attempts + 1,
                        last_attempt_at = now(),
                        resolved_at = CASE WHEN %s IS NULL THEN now() ELSE NULL END
                    WHERE source = %s AND device_id = %s AND firebase_id = %s;
                    """,
                    (
                        reason, reason, rejection.source,
                        rejection.device_id, rejection.firebase_id,
                    ),
                )
            self.database.commit()
        except Exception:
            self.database.rollback()
            raise
