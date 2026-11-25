"""Backup somente de dados e restauração restrita a destino local vazio.

Requer Docker e imagem postgres:18.7. Nunca restaura DDL ou extensões do dump.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from app.config.config import config
from app.database.connection import DatabaseConnection
from app.operations.reconcile import TABLES, digest, read_tables, write_private


IMAGE = "postgres:18.7"
LOOPBACK = ("localhost", "127.0.0.1", "::1")


def fingerprints(tables):
    return {
        table: {"count": len(rows), "sha256": digest(sorted(rows, key=digest))}
        for table, rows in tables.items()
    }


@contextmanager
def service_profile(parameters):
    with tempfile.TemporaryDirectory(prefix="etl-pg-service-", dir="/tmp/opencode") as folder:
        root = Path(folder)
        values = {
            "host": parameters["host"], "port": str(parameters["port"]),
            "dbname": parameters["dbname"], "user": parameters["user"],
            "password": parameters["password"], "sslmode": parameters["sslmode"],
            "connect_timeout": str(parameters["connect_timeout"]),
        }
        if parameters.get("sslrootcert"):
            shutil.copyfile(parameters["sslrootcert"], root / "ca.crt")
            values["sslrootcert"] = "/run/etl-auth/ca.crt"
        if any("\n" in str(value) or "\r" in str(value) for value in values.values()):
            raise ValueError("Valores multilinha não são aceitos no perfil libpq.")
        profile = root / "service.conf"
        profile.write_text("[etl]\n" + "".join(f"{key}={value}\n" for key, value in values.items()))
        profile.chmod(0o600)
        yield root


def postgres_tool(parameters, directory, arguments, readonly=False):
    with service_profile(parameters) as profile:
        command = [
            "docker", "run", "--rm", "--network", "host",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,src={profile},dst=/run/etl-auth,readonly",
            "--mount", f"type=bind,src={Path(directory).resolve()},dst=/artifacts"
            + (",readonly" if readonly else ""),
            "--env", "PGSERVICEFILE=/run/etl-auth/service.conf", IMAGE, *arguments,
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if result.returncode:
            # Não incluir parâmetros/credenciais da conexão no erro.
            message = result.stderr.replace(parameters["password"], "[REDACTED]")
            raise RuntimeError(f"Ferramenta PostgreSQL falhou: {message}")
        return result.stdout


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_backup(output):
    output = Path(output)
    if output.exists():
        raise ValueError("Backup exige diretório novo; não sobrescrever evidências.")
    parameters = config.database_parameters()
    if config.POSTGRES_HOST not in LOOPBACK and config.POSTGRES_SSLMODE != "verify-full":
        raise ValueError("Backup remoto exige verify-full.")
    output.mkdir(parents=True, mode=0o700)
    database = DatabaseConnection()
    try:
        with database.exclusive():
            connection = database.connect()
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute("SELECT pg_export_snapshot(), current_setting('server_version')")
                snapshot, version = cursor.fetchone()
            before = fingerprints(read_tables(connection))
            postgres_tool(parameters, output, [
                "pg_dump", "--dbname=service=etl", f"--schema={config.POSTGRES_SCHEMA}",
                "--format=custom", "--data-only", "--no-owner", "--no-privileges",
                "--strict-names", "--lock-wait-timeout=10000",
                f"--snapshot={snapshot}", "--file=/artifacts/data.dump",
            ])
            archive = output / "data.dump"
            archive.chmod(0o600)
            toc = postgres_tool(parameters, output, [
                "pg_restore", "--list", "/artifacts/data.dump",
            ], readonly=True)
            entries = [
                line for line in toc.splitlines() if line and not line.startswith(";")
            ]
            if len(entries) != 4 or any(
                f"TABLE DATA {config.POSTGRES_SCHEMA} {table} " not in "\n".join(entries)
                for table in TABLES
            ):
                raise ValueError("O dump não contém exatamente as quatro tabelas de dados.")
            write_private(output / "toc.json", entries)
            manifest = {
                "captured_at": datetime.now(timezone.utc),
                "postgres_version": version, "schema": config.POSTGRES_SCHEMA,
                "kind": "data_only", "archive_sha256": file_hash(archive),
                "tables": before,
                "migrations": {
                    path.name: file_hash(path)
                    for path in sorted(Path("app/sql/migrations").glob("*.sql"))
                },
            }
            write_private(output / "manifest.json", manifest)
            return manifest
    finally:
        database.close()


def restore_empty_local(backup, confirmed=False):
    import json
    if not confirmed or config.POSTGRES_HOST not in LOOPBACK:
        raise ValueError("Restauração exige confirmação e host local descartável.")
    backup = Path(backup)
    manifest = json.loads((backup / "manifest.json").read_text())
    if manifest["kind"] != "data_only" or manifest["schema"] != config.POSTGRES_SCHEMA:
        raise ValueError("Manifesto incompatível com o destino.")
    if file_hash(backup / "data.dump") != manifest["archive_sha256"]:
        raise ValueError("Checksum do backup divergente.")
    for name, checksum in manifest["migrations"].items():
        if file_hash(Path("app/sql/migrations") / name) != checksum:
            raise ValueError("Migrações atuais diferem das utilizadas no backup.")
    parameters = config.database_parameters()
    database = DatabaseConnection()
    try:
        with database.exclusive():
            connection = database.connect()
            current = fingerprints(read_tables(connection))
            if any(item["count"] for item in current.values()):
                raise ValueError("Destino não vazio: restauração recusada sem apagar dados.")
            connection.rollback()
            postgres_tool(parameters, backup, [
                "pg_restore", "--dbname=service=etl", "--data-only",
                "--single-transaction", "--exit-on-error", "--no-owner",
                "--no-privileges", "/artifacts/data.dump",
            ], readonly=True)
            after = fingerprints(read_tables(connection))
            if after != manifest["tables"]:
                raise ValueError("Conteúdo restaurado diverge do manifesto; preservar para inspeção.")
            return {"passed": True, "tables": after}
    finally:
        database.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backup", "restore"))
    parser.add_argument("--directory", required=True)
    parser.add_argument("--confirm-empty-local", action="store_true")
    args = parser.parse_args()
    result = (
        create_backup(args.directory) if args.operation == "backup"
        else restore_empty_local(args.directory, args.confirm_empty_local)
    )
    print(args.operation, {table: item["count"] for table, item in result["tables"].items()})


if __name__ == "__main__":
    main()
