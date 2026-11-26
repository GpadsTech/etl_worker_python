"""Reconciliação somente leitura: Firebase capturado x PostgreSQL."""

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from psycopg2 import sql

from app.config.config import config
from app.database.connection import DatabaseConnection
from app.firebase.client import FirebaseClient
from app.repository.sensor_repository import SensorRepository
from app.repository.buoy_repository import BuoyRepository
from app.transformer.normalize import normalize_sensor, normalize_buoy
from app.transformer.timestamp import SOURCE_TIMEZONE


SOURCES = {
    "sensores": (SensorRepository, normalize_sensor, "sensor_id"),
    "boias": (BuoyRepository, normalize_buoy, "buoy_id"),
}
TABLES = ("sensor_data", "buoy_data", "etl_checkpoint", "etl_rejections")


def canonical(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Reconciliação exige instantes com fuso.")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(item) for item in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(
        canonical(value), sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":"),
    ).encode()).hexdigest()


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Os artefatos contêm dados reais e não devem ser publicados.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(canonical(value), output, ensure_ascii=False, indent=2, allow_nan=False)
    path.chmod(0o600)


def capture_firebase(client=None):
    client = client or FirebaseClient()
    result = {}
    for source, root, reference in (
        ("sensores", client.sensors, client.sensor_data),
        ("boias", client.buoys, client.buoy_data),
    ):
        devices = root().get(shallow=True)
        if devices is None:
            devices = {}
        if not isinstance(devices, dict):
            raise ValueError("Raiz Firebase inválida; não tratar como origem vazia.")
        result[source] = {}
        for device in sorted(devices):
            records = reference(device).order_by_key().get()
            if records is None:
                records = {}
            if not isinstance(records, dict):
                raise ValueError("Histórico Firebase inválido.")
            result[source][device] = records
    return result


def select_scope(snapshot, per_device=None):
    if per_device is not None and per_device < 1:
        raise ValueError("O limite por equipamento deve ser positivo.")
    return {
        source: {
            device: dict(sorted(records.items())[:per_device])
            for device, records in devices.items()
        }
        for source, devices in snapshot.items()
    }


def snapshot_delta(previous, current):
    result = {}
    for source in SOURCES:
        for device in sorted(set(previous.get(source, {})) | set(current.get(source, {}))):
            before = previous.get(source, {}).get(device, {})
            after = current.get(source, {}).get(device, {})
            added = sorted(after.keys() - before.keys())
            removed = sorted(before.keys() - after.keys())
            changed = sorted(
                key for key in before.keys() & after.keys()
                if digest(before[key]) != digest(after[key])
            )
            result[f"{source}/{device}"] = {
                "added": added, "removed": removed, "changed": changed,
                "late_added": [key for key in added if before and key <= max(before)],
            }
    return {
        "before_sha256": digest(previous), "after_sha256": digest(current),
        "devices": result,
        "added_count": sum(len(row["added"]) for row in result.values()),
        "removed_count": sum(len(row["removed"]) for row in result.values()),
        "changed_count": sum(len(row["changed"]) for row in result.values()),
        "late_added_count": sum(len(row["late_added"]) for row in result.values()),
    }


def expected_rows(snapshot):
    tables = {}
    invalid = []
    checkpoints = []
    for source, (repository, normalize, device_column) in SOURCES.items():
        rows = []
        for device, records in sorted(snapshot.get(source, {}).items()):
            if records:
                checkpoints.append({
                    "source": source, "device_id": device, "last_key": max(records),
                })
            for firebase_id, payload in sorted(records.items()):
                try:
                    if not isinstance(payload, dict):
                        raise ValueError("A leitura deve ser objeto JSON.")
                    obj = normalize(
                        firebase_id=firebase_id, **{device_column: device}, data=payload,
                    )
                    rows.append(canonical(asdict(obj)))
                except (ValueError, KeyError, TypeError, OverflowError) as error:
                    invalid.append({
                        "source": source, "device_id": device, "firebase_id": firebase_id,
                        "error_type": type(error).__name__,
                    })
        tables[repository.table_name] = rows
    return tables, checkpoints, invalid


def read_tables(connection, schema=None, include_audit=False):
    schema = schema or config.POSTGRES_SCHEMA
    result = {}
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'UTC'")
        tables = TABLES
        if include_audit:
            cursor.execute("SELECT to_regclass(%s)", (f"{schema}.etl_corrections",))
            if cursor.fetchone()[0] is not None:
                tables += ("etl_corrections",)
        for table in tables:
            cursor.execute(sql.SQL("SELECT to_jsonb(t) FROM {}.{} t").format(
                sql.Identifier(schema), sql.Identifier(table),
            ))
            result[table] = sorted(
                [row[0] for row in cursor.fetchall()],
                key=lambda row: json.dumps(row, sort_keys=True),
            )
    return result


def measurement_rows(rows):
    # PostgreSQL JSON e Python usam representações distintas do mesmo offset UTC.
    result = []
    for row in rows:
        row = dict(row)
        row["timestamp"] = datetime.fromisoformat(row["timestamp"])
        result.append(canonical(row))
    return result


def metrics(rows, device_column):
    by_device = {}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[device_column]].append(row)
    for device, records in sorted(grouped.items()):
        records = sorted(records, key=lambda row: row["firebase_id"])
        instants = [datetime.fromisoformat(row["timestamp"]) for row in records]
        by_device[device] = {
            "count": len(records),
            "min_utc": min(instants), "max_utc": max(instants),
            "by_day_America_Sao_Paulo": dict(sorted(Counter(
                instant.astimezone(SOURCE_TIMEZONE).date().isoformat()
                for instant in instants
            ).items())),
            "nulls": {
                column: sum(row.get(column) is None for row in records)
                for column in sorted({column for row in records for column in row})
            },
            "samples": [records[index] for index in sorted({
                0, len(records) // 2, len(records) - 1,
            })],
        }
    return canonical({"count": len(rows), "devices": by_device})


def compare(snapshot, actual, per_device=None):
    selected = select_scope(snapshot, per_device)
    expected, checkpoints, invalid = expected_rows(selected)
    report = {
        "source_timezone": SOURCE_TIMEZONE.key,
        "scope": "all_captured_records" if per_device is None else f"first_{per_device}_keys_per_device",
        "snapshot_sha256": digest(snapshot), "tables": {}, "invalid_source": invalid,
    }
    differences = 0
    for source, (repository, _, device_column) in SOURCES.items():
        table = repository.table_name
        wanted = expected[table]
        found = measurement_rows(actual[table])
        key = lambda row: (row[device_column], row["firebase_id"])
        if per_device is not None:
            scope_keys = {
                (device, record_id)
                for device, records in selected.get(source, {}).items()
                for record_id in records
            }
            found = [row for row in found if key(row) in scope_keys]
        left = {key(row): row for row in wanted}
        right = {key(row): row for row in found}
        missing = sorted(left.keys() - right.keys())
        extra = sorted(right.keys() - left.keys())
        changed = [
            {"key": item, "fields": [
                field for field in sorted(left[item].keys() | right[item].keys())
                if field not in left[item] or field not in right[item]
                or left[item][field] != right[item][field]
            ]}
            for item in sorted(left.keys() & right.keys()) if left[item] != right[item]
        ]
        duplicates = len(found) - len(right)
        differences += len(missing) + len(extra) + len(changed) + duplicates
        report["tables"][table] = {
            "expected": metrics(wanted, device_column),
            "actual": metrics(found, device_column),
            "missing": missing, "extra": extra, "changed": changed,
            "duplicate_keys": duplicates,
        }
    # Checkpoint e rejeições são estado do ETL, não medições do Firebase.
    report["state"] = {
        "checkpoint_count": len(actual["etl_checkpoint"]),
        "checkpoints": actual["etl_checkpoint"],
        "rejection_count": len(actual["etl_rejections"]),
        "pending_rejections": sum(row["resolved_at"] is None for row in actual["etl_rejections"]),
        "internal_table_metrics": {
            table: metrics([
                dict(row, timestamp=row[instant], firebase_id=row.get("firebase_id", row.get("last_key")))
                for row in actual[table]
            ], "device_id")
            for table, instant in (("etl_checkpoint", "updated_at"), ("etl_rejections", "created_at"))
        },
    }
    pending_keys = {
        (row["source"], row["device_id"], row["firebase_id"])
        for row in actual["etl_rejections"] if row["resolved_at"] is None
    }
    if per_device is None:
        invalid_keys = {
            (row["source"], row["device_id"], row["firebase_id"]) for row in invalid
        }
        report["state"]["pending_rejections_explained"] = pending_keys == invalid_keys
        differences += len(pending_keys ^ invalid_keys)
    if per_device is None:
        expected_checkpoint = {(r["source"], r["device_id"]): r["last_key"] for r in checkpoints}
        actual_checkpoint = {
            (r["source"], r["device_id"]): r["last_key"] for r in actual["etl_checkpoint"]
        }
        report["state"]["checkpoints_match"] = expected_checkpoint == actual_checkpoint
        differences += int(expected_checkpoint != actual_checkpoint)
    # Falhas da origem nunca são silenciosamente consideradas reconciliadas.
    report["unexplained_differences"] = differences
    report["passed"] = differences == 0 and not invalid
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Diretório privado para evidências.")
    parser.add_argument("--previous", help="Snapshot Firebase anterior para reconciliar o delta.")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError("Escolha um diretório novo para preservar evidências anteriores.")
    output.mkdir(parents=True, mode=0o700)
    database = DatabaseConnection()
    try:
        started = datetime.now(timezone.utc)
        with database.exclusive():
            # Não altera origem nem destino. O lock pausa escritores cooperantes no destino.
            before = capture_firebase()
            with database.connect().cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            actual = read_tables(database.connect())
            after = capture_firebase()
        stable = digest(before) == digest(after)
        write_private(output / "firebase.json", before)
        write_private(output / "postgres.json", actual)
        reports = {}
        for name, limit in (("small", 100), ("full", None)):
            report = compare(before, actual, limit)
            report.update({
                "captured_from": started, "captured_until": datetime.now(timezone.utc),
                "source_stable_during_capture": stable,
            })
            report["passed"] = report["passed"] and stable
            reports[name] = report
            write_private(output / f"{name}.json", report)
            print(name, "OK" if report["passed"] else "DIVERGÊNCIA",
                  {table: r["actual"]["count"] for table, r in report["tables"].items()})
        if args.previous:
            write_private(output / "delta.json", snapshot_delta(
                json.loads(Path(args.previous).read_text()), before,
            ))
        write_daily_csv(output / "daily.csv", reports["full"])
        raise SystemExit(0 if all(r["passed"] for r in reports.values()) else 1)
    finally:
        database.close()


def write_daily_csv(path, report):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("table", "equipment", "day_America_Sao_Paulo",
                         "firebase_count", "postgres_count", "difference"))
        for table, comparison in report["tables"].items():
            left = comparison["expected"]["devices"]
            right = comparison["actual"]["devices"]
            for device in sorted(left.keys() | right.keys()):
                expected = left.get(device, {}).get("by_day_America_Sao_Paulo", {})
                actual = right.get(device, {}).get("by_day_America_Sao_Paulo", {})
                for day in sorted(expected.keys() | actual.keys()):
                    a, b = expected.get(day, 0), actual.get(day, 0)
                    writer.writerow((table, device, day, a, b, b - a))


if __name__ == "__main__":
    main()
