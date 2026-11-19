"""
Carrega as configurações da aplicação
"""

from dotenv import load_dotenv
import os
import re
from pathlib import Path

env_file = os.getenv("ETL_ENV_FILE")
if env_file and not Path(env_file).is_file():
    raise ValueError("ETL_ENV_FILE deve indicar um arquivo existente.")
load_dotenv(dotenv_path=env_file or None)


class Config:

    @staticmethod
    def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(os.getenv(name) or default)
        except ValueError:
            raise ValueError(f"{name} deve ser um inteiro.") from None
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} deve estar entre {minimum} e {maximum}.")
        return value

    def __init__(self):

        self.FIREBASE_DATABASE_URL = os.getenv(
            "FIREBASE_DATABASE_URL",
            ""
        )

        self.FIREBASE_CREDENTIALS = os.getenv(
            "FIREBASE_CREDENTIALS",
            ""
        )

        self.POSTGRES_HOST = os.getenv(
            "POSTGRES_HOST",
            ""
        )

        self.POSTGRES_PORT = self._integer("POSTGRES_PORT", 5432, 1, 65535)

        self.POSTGRES_DB = os.getenv(
            "POSTGRES_DB",
            ""
        )

        self.POSTGRES_USER = os.getenv(
            "POSTGRES_USER",
            ""
        )

        self.POSTGRES_PASSWORD = os.getenv(
            "POSTGRES_PASSWORD",
            ""
        )

        local = self.POSTGRES_HOST in ("localhost", "127.0.0.1", "::1")
        self.POSTGRES_SSLMODE = os.getenv(
            "POSTGRES_SSLMODE", "disable" if local else "verify-full",
        )
        self.POSTGRES_SSLROOTCERT = os.getenv("POSTGRES_SSLROOTCERT", "")
        self.POSTGRES_SCHEMA = os.getenv("POSTGRES_SCHEMA", "etl_private")
        self.POSTGRES_CONNECT_TIMEOUT = self._integer(
            "POSTGRES_CONNECT_TIMEOUT", 10, 1, 2147483647,
        )
        self.POSTGRES_STATEMENT_TIMEOUT_MS = self._integer(
            "POSTGRES_STATEMENT_TIMEOUT_MS", 60000, 0, 2147483647,
        )
        self.POSTGRES_LOCK_TIMEOUT_MS = self._integer(
            "POSTGRES_LOCK_TIMEOUT_MS", 5000, 0, 2147483647,
        )

        self.ETL_INTERVAL_SECONDS = int(
            os.getenv("ETL_INTERVAL_SECONDS") or 60
        )

    def database_parameters(self) -> dict:
        """Valida configuração e monta parâmetros libpq sem registrar segredos."""
        for name in (
            "POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD",
        ):
            if not getattr(self, name):
                raise ValueError(f"Defina {name} antes de conectar.")
        if self.POSTGRES_SSLMODE not in (
            "disable", "allow", "prefer", "require", "verify-ca", "verify-full",
        ):
            raise ValueError("POSTGRES_SSLMODE inválido.")
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.POSTGRES_SCHEMA):
            raise ValueError("POSTGRES_SCHEMA deve ser um identificador SQL simples em minúsculas.")
        parameters = {
            "host": self.POSTGRES_HOST,
            "port": self.POSTGRES_PORT,
            "dbname": self.POSTGRES_DB,
            "user": self.POSTGRES_USER,
            "password": self.POSTGRES_PASSWORD,
            "sslmode": self.POSTGRES_SSLMODE,
            "connect_timeout": self.POSTGRES_CONNECT_TIMEOUT,
            "options": (
                f"-c statement_timeout={self.POSTGRES_STATEMENT_TIMEOUT_MS} "
                f"-c lock_timeout={self.POSTGRES_LOCK_TIMEOUT_MS} "
                f"-c search_path={self.POSTGRES_SCHEMA},pg_catalog"
            ),
        }
        if self.POSTGRES_SSLROOTCERT:
            path = Path(self.POSTGRES_SSLROOTCERT)
            if not path.is_file() or not os.access(path, os.R_OK):
                raise ValueError("POSTGRES_SSLROOTCERT deve indicar um arquivo legível.")
            parameters["sslrootcert"] = str(path)
        return parameters


config = Config()
