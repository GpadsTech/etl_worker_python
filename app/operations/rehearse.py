"""Ensaio isolado com snapshot real e delta controlado, sem escrever no Firebase."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid

from dotenv import dotenv_values, set_key

from app.config.config import config
from app.database.connection import DatabaseConnection, WorkerAlreadyRunningError
from app.operations.backup import LOOPBACK
from app.operations.reconcile import (
    compare, digest, read_tables, select_scope, write_private,
)
from app.worker.etl_worker import ETLWorker


class Query:
    def __init__(self, records, start=None):
        self.records = records
        self.start = start

    def order_by_key(self):
        return self

    def start_at(self, value):
        return Query(self.records, value)

    def get(self, shallow=False):
        return {
            key: True if shallow else value for key, value in sorted(self.records.items())
            if self.start is None or key >= self.start
        }


class SnapshotSource:
    """Interface de leitura do worker; não contém método de escrita na origem."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.connections = 0

    def connect(self):
        self.connections += 1

    def sensors(self):
        return Query(self.snapshot["sensores"])

    def buoys(self):
        return Query(self.snapshot["boias"])

    def sensor_data(self, device):
        return Query(self.snapshot["sensores"][device])

    def buoy_data(self, device):
        return Query(self.snapshot["boias"][device])


def child(env_file, module, *arguments):
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("POSTGRES_", "FIREBASE_"))
        and key not in ("ETL_ENV_FILE", "ETL_INTERVAL_SECONDS")
    }
    environment["ETL_ENV_FILE"] = str(Path(env_file).resolve())
    result = subprocess.run(
        [sys.executable, "-m", module, *map(str, arguments)],
        env=environment, capture_output=True, text=True, timeout=300,
    )
    if result.returncode:
        message = (result.stdout + result.stderr)[-2500:]
        for key, value in dotenv_values(env_file).items():
            if value and any(word in key.upper() for word in ("PASSWORD", "TOKEN", "SECRET")):
                message = message.replace(value, "[REDACTED]")
        raise RuntimeError(f"Etapa {module} falhou ({result.returncode}): {message}")
    return result.stdout


def actor(args):
    if config.POSTGRES_HOST not in LOOPBACK or not config.POSTGRES_DB.startswith("t04_"):
        raise ValueError("Ator exige banco local descartável com prefixo t04_.")
    snapshot = select_scope(json.loads(Path(args.snapshot).read_text()), args.per_device)
    if args.withhold_last:
        snapshot = {
            source: {
                device: dict(sorted(records.items())[:-args.withhold_last])
                for device, records in devices.items()
            } for source, devices in snapshot.items()
        }
    worker = ETLWorker()
    worker.firebase = SnapshotSource(snapshot)
    worker.logger.disabled = True
    try:
        if args.action == "probe":
            try:
                worker.run_once()
            except WorkerAlreadyRunningError:
                if worker.firebase.connections:
                    raise ValueError("Origem consultada antes da exclusão.")
                write_private(args.output, {"blocked": True, "pid": os.getpid()})
                return
            raise ValueError("Segundo processo não foi bloqueado.")
        if args.action == "lock-test":
            with worker.database.exclusive():
                child(
                    os.environ["ETL_ENV_FILE"], "app.operations.rehearse", "actor",
                    "--snapshot", args.snapshot, "--action", "probe", "--output", args.output,
                )
            result = json.loads(Path(args.output).read_text())
            if result["pid"] == os.getpid() or not result["blocked"]:
                raise ValueError("Disputa de processos não comprovada.")
            result["holder_pid"] = os.getpid()
            write_private(args.output, result)
            return
        if args.action == "replay":
            # Volta o checkpoint, não apaga medições: simula falha após commit dos dados.
            with worker.database.exclusive():
                for source, devices in snapshot.items():
                    for device, records in devices.items():
                        if records:
                            worker.checkpoints.set(source, device, min(records))
        counters = worker.run_once()
        if any(item[3] for item in counters):
            raise ValueError("Ator registrou erro no ETL.")
        with worker.database.exclusive():
            report = compare(snapshot, read_tables(worker.database.connect()))
        report["counters"] = counters
        report["pid"] = os.getpid()
        write_private(args.output, report)
        if not report["passed"]:
            raise ValueError("Reconciliação do ensaio divergente.")
    finally:
        worker.database.close()


def run_rehearsal(args):
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("Ensaio exige diretório de saída novo.")
    output.mkdir(parents=True, mode=0o700)
    snapshot = str(Path(args.snapshot).resolve())
    # Cada execução usa cluster novo; o ensaio nunca aponta para o banco real.
    name = "etl-t04-" + uuid.uuid4().hex[:10]
    password = secrets.token_urlsafe(32)
    container_env = output / "container.env"
    write_private(container_env, {})  # estabelece modo 0600 antes de gravar o segredo.
    container_env.write_text(f"POSTGRES_PASSWORD={password}\n")
    sql_root = Path("app/sql").resolve()
    started = False

    def docker(*arguments, timeout=60):
        result = subprocess.run(
            ["docker", *map(str, arguments)], capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError(f"Docker falhou: {result.stderr.replace(password, '[REDACTED]')}")
        return result.stdout.strip()

    def provision(database):
        docker("exec", name, "createdb", "-U", "postgres", database)
        docker("exec", name, "psql", "-U", "postgres", "-d", database,
               "-v", "ON_ERROR_STOP=1", "-f", "/docker-entrypoint-initdb.d/schema.sql")
        env_file = output / f"{database}.env"
        env_file.touch(mode=0o600)
        for key, value in {
            "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": port,
            "POSTGRES_DB": database, "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": password, "POSTGRES_SCHEMA": "etl_private",
            "POSTGRES_SSLMODE": "disable", "POSTGRES_SSLROOTCERT": "",
        }.items():
            set_key(str(env_file), key, str(value))
        return env_file

    def stage(env_file, target, limit=None, withheld=False, action="run"):
        arguments = ["actor", "--snapshot", snapshot, "--output", target, "--action", action]
        if limit:
            arguments += ["--per-device", str(limit)]
        if withheld:
            arguments += ["--withhold-last", "1"]
        child(env_file, "app.operations.rehearse", *arguments)
        return json.loads(Path(target).read_text())

    try:
        docker(
            "run", "--rm", "--detach", "--name", name, "--env-file", container_env,
            "-p", "127.0.0.1::5432", "--mount",
            f"type=bind,src={sql_root},dst=/docker-entrypoint-initdb.d,readonly",
            "postgres:18.7",
        )
        started = True
        deadline = time.monotonic() + 60
        while True:
            ready = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Banco descartável não ficou pronto.")
            time.sleep(0.25)
        port = docker("port", name, "5432").rsplit(":", 1)[1]
        restored = provision("t04_source_backup_restore")
        child(restored, "app.operations.backup", "restore", "--directory",
              Path(args.source_backup).resolve(), "--confirm-empty-local")
        restored_report = stage(restored, output / "source-backup-restored.json")
        if any(item[1] for item in restored_report["counters"]):
            raise ValueError("Backup de origem não estava completo no recorte capturado.")
        summary = {"source_backup_restored": True, "cases": {}}
        for label, limit in (("small", 100), ("full", None)):
            active = provision(f"t04_{label}_active")
            returned = provision(f"t04_{label}_returned")
            baseline = stage(active, output / f"{label}-baseline.json", limit, True)
            backup = output / f"{label}-backup"
            child(active, "app.operations.backup", "backup", "--directory", backup)
            lock = stage(active, output / f"{label}-lock.json", action="lock-test")
            delta = stage(active, output / f"{label}-delta.json", limit)
            resumed = stage(active, output / f"{label}-resumed.json", limit)
            replay = stage(active, output / f"{label}-replay.json", limit, action="replay")
            if any(item[1] for item in resumed["counters"] + replay["counters"]):
                raise ValueError("Retomada/replay duplicou medições.")
            # O processo ativo já encerrou antes de provisionar o ambiente de retorno.
            child(returned, "app.operations.backup", "restore", "--directory", backup,
                  "--confirm-empty-local")
            recovered = stage(returned, output / f"{label}-recovered.json", limit)
            if delta["counters"] != recovered["counters"]:
                raise ValueError("Delta do retorno não reproduziu a passagem original.")
            summary["cases"][label] = {
                "baseline_inserted": sum(item[1] for item in baseline["counters"]),
                "delta_inserted": sum(item[1] for item in delta["counters"]),
                "returned_delta_inserted": sum(item[1] for item in recovered["counters"]),
                "final_count": sum(r["actual"]["count"] for r in recovered["tables"].values()),
                "replay_inserted": sum(item[1] for item in replay["counters"]),
                "second_process_blocked": lock["blocked"],
                "passed": all(r["passed"] for r in (baseline, delta, resumed, replay, recovered)),
            }
        summary["snapshot_sha256"] = digest(json.loads(Path(snapshot).read_text()))
        summary["delta_kind"] = "controlled: last key per device withheld from baseline; no Firebase writes"
        write_private(output / "summary.json", summary)
        print(json.dumps(summary, indent=2))
    finally:
        try:
            if started:
                docker("stop", name)
        finally:
            # Só remove arquivos próprios no diretório novo desta execução.
            for path in output.glob("*.env"):
                path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--snapshot", required=True)
    run.add_argument("--source-backup", required=True)
    run.add_argument("--output", required=True)
    step = commands.add_parser("actor")
    step.add_argument("--snapshot", required=True)
    step.add_argument("--output", required=True)
    step.add_argument("--per-device", type=int)
    step.add_argument("--withhold-last", type=int, default=0)
    step.add_argument("--action", choices=("run", "replay", "lock-test", "probe"), default="run")
    args = parser.parse_args()
    if args.command == "actor":
        actor(args)
    else:
        run_rehearsal(args)


if __name__ == "__main__":
    main()
