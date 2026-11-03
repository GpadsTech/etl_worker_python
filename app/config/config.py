"""
Carrega as configurações da aplicação
"""

from dotenv import load_dotenv
import os

load_dotenv()


class Config:

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

        self.POSTGRES_PORT = int(
            os.getenv("POSTGRES_PORT") or 5432
        )

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

        self.ETL_INTERVAL_SECONDS = int(
            os.getenv("ETL_INTERVAL_SECONDS") or 60
        )


config = Config()