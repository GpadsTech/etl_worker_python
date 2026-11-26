"""Recuperação histórica limitada e correção administrativa explícita."""

import argparse
import uuid

from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor

from app.firebase.pagination import iter_pages, validate_key
from app.operations.reconcile import SOURCES, canonical, digest
from app.worker.etl_worker import ETLWorker, exclusive_operation


@exclusive_operation
def backfill(worker, source, device_id, start, end):
    """Reprocessa apenas IDs desconhecidos; nunca altera o checkpoint."""
    validate_key(start)
    validate_key(end)
    if start > end:
        raise ValueError("Intervalo invertido.")
    worker.firebase.connect()
    reference = (worker.firebase.sensor_data if source == "sensores"
                 else worker.firebase.buoy_data)(device_id)
    _, normalize, id_field = SOURCES[source]
    repository = worker.sensor_repository if source == "sensores" else worker.buoy_repository
    totals = [0, 0, 0, 0]
    for page in iter_pages(reference, worker.page_size, start=start, end=end):
        counts, durable = worker._persist_unseen(
            source, device_id, page, normalize, id_field, repository,
        )
        totals = [a + b for a, b in zip(totals, counts)]
        if not durable:
            raise RuntimeError("Página não confirmada; repetir o mesmo intervalo é seguro.")
    return tuple(totals)


@exclusive_operation
def correct(worker, source, device_id, key, reason, expected_hash=None, apply=False,
            expected_source_hash=None):
    """Atualização e auditoria na mesma transação; prévia é o padrão."""
    validate_key(key)
    if not reason.strip():
        raise ValueError("Informe o motivo da correção.")
    repository_type, normalize, id_field = SOURCES[source]
    worker.firebase.connect()
    reference = (worker.firebase.sensor_data if source == "sensores"
                 else worker.firebase.buoy_data)(device_id)
    payload = reference.child(key).get()
    if not isinstance(payload, dict):
        raise ValueError("Leitura ausente ou inválida na origem.")
    obj = normalize(firebase_id=key, **{id_field: device_id}, data=payload)
    after = {column: getattr(obj, column) for column in repository_type.columns}
    connection = worker.database.connect()
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql.SQL(
                "SELECT * FROM {} WHERE {}=%s AND firebase_id=%s FOR UPDATE"
            ).format(sql.Identifier(repository_type.table_name), sql.Identifier(id_field)),
                (device_id, key))
            before = cursor.fetchone()
            if before is None:
                raise ValueError("Medição não existe; use backfill ou reprocessamento de rejeições.")
            before = dict(before)
            old_hash, new_hash = digest(before), digest(after)
            result = {"before_sha256": old_hash, "after_sha256": new_hash,
                      "changed": old_hash != new_hash, "applied": False}
            if apply:
                if expected_hash != old_hash:
                    raise ValueError("Hash anterior divergente; refaça a prévia.")
                if expected_source_hash != new_hash:
                    raise ValueError("Hash da origem divergente; refaça a prévia.")
                if old_hash == new_hash:
                    return result
                mutable = [column for column in repository_type.columns
                           if column not in (id_field, "firebase_id")]
                cursor.execute(sql.SQL("UPDATE {} SET {} WHERE {}=%s AND firebase_id=%s").format(
                    sql.Identifier(repository_type.table_name),
                    sql.SQL(", ").join(sql.SQL("{}=%s").format(sql.Identifier(column))
                                      for column in mutable),
                    sql.Identifier(id_field),
                ), [after[column] for column in mutable] + [device_id, key])
                cursor.execute(
                    "INSERT INTO etl_corrections "
                    "(correction_id, source, device_id, firebase_id, reason, before_row, after_row) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (str(uuid.uuid4()), source, device_id, key, reason,
                     Json(canonical(before)), Json(canonical(after))),
                )
                worker.database.commit()
                result["applied"] = True
            return result
    finally:
        # Também libera locks da prévia e desfaz UPDATE se auditoria falhar.
        worker.database.rollback()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backfill", "correct"))
    parser.add_argument("--source", required=True, choices=tuple(SOURCES))
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--key")
    parser.add_argument("--reason")
    parser.add_argument("--expected-hash")
    parser.add_argument("--expected-source-hash")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.operation == "backfill":
        if (not args.start or not args.end or args.apply or args.key
                or args.expected_hash or args.expected_source_hash):
            parser.error("backfill exige --start/--end, sem opções de correção.")
    elif (not args.key or not args.reason or args.start or args.end or
          (args.apply and (not args.expected_hash or not args.expected_source_hash))):
        parser.error("correct exige --key/--reason e, para --apply, os dois hashes da prévia.")
    worker = ETLWorker()
    try:
        if args.operation == "backfill":
            print(backfill(worker, args.source, args.device_id, args.start, args.end))
        else:
            print(correct(worker, args.source, args.device_id, args.key,
                          args.reason, args.expected_hash, args.apply,
                          args.expected_source_hash))
        return 0
    except Exception as error:
        # Diagnósticos SQL podem conter payloads; não imprimir traceback bruto.
        worker.logger.error(f"Falha no reprocessamento histórico | Tipo: {type(error).__name__}")
        return 1
    finally:
        worker.database.close()


if __name__ == "__main__":
    raise SystemExit(main())
