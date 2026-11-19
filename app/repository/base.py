"""
Base para os repositórios ativos de persistência.

Política de conflito: histórico append-only.

A chave primária é ``(equipamento, firebase_id)`` e as inserções usam
``ON CONFLICT DO NOTHING``. O banco guarda a primeira versão recebida de
cada leitura; correções feitas no Firebase não são aplicadas. Essa é uma
decisão explícita do projeto: não há upsert nem reconciliação enquanto a
operação não exigir correções.

O firebase_id não é reutilizado dentro de um equipamento. Alterações de
timestamp ou payload da mesma leitura não criam uma nova linha.

A chave primária não deve ser alterada para ``(equipamento, timestamp)``:
existem leituras reais com o mesmo ``hora`` e ``firebase_id`` diferentes
(ex.: 26 registros da BOIA001 em 2026-07-21 00:00:00), que seriam
descartadas pela política de conflito.
"""

from psycopg2.extras import execute_values

from app.database.connection import DatabaseConnection


BATCH_SIZE = 500


class BaseRepository:
    """
    Insere objetos de domínio em lote, uma transação por chamada.
    """

    table_name: str = ""
    columns: tuple[str, ...] = ()
    conflict_columns: tuple[str, ...] = ()

    def __init__(self, database: DatabaseConnection):
        self.database = database

    def _values(self, obj) -> tuple:
        return tuple(
            getattr(obj, column)
            for column in self.columns
        )

    def insert(self, obj) -> bool:
        """
        Insere um único registro.

        Retorna True se a linha foi criada e False se já existia.
        """

        return self.insert_many([obj]) == 1

    def insert_many(self, objects) -> int:
        """
        Insere vários registros em lote.

        Retorna a quantidade de linhas efetivamente criadas. Registros
        já existentes são ignorados pela chave primária. Em caso de
        erro, a transação inteira é revertida e a exceção é propagada.
        """

        objects = list(objects)

        if not objects:
            return 0

        connection = self.database.connect()

        inserted = 0

        query = f"""
            INSERT INTO {self.table_name}
            ({", ".join(self.columns)})
            VALUES %s
            ON CONFLICT ({", ".join(self.conflict_columns)})
            DO NOTHING
            RETURNING firebase_id;
        """

        try:

            with connection.cursor() as cursor:

                for start in range(0, len(objects), BATCH_SIZE):

                    chunk = objects[start:start + BATCH_SIZE]

                    execute_values(
                        cursor,
                        query,
                        [self._values(obj) for obj in chunk],
                        page_size=len(chunk),
                    )

                    inserted += len(cursor.fetchall())

            self.database.commit()

            return inserted

        except Exception:

            self.database.rollback()

            raise
