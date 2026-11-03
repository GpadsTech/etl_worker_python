"""
Faz a  comunicação com o
Firebase Realtime Database.
"""

from pathlib import Path

import firebase_admin

from firebase_admin import credentials
from firebase_admin import db

from app.config.config import config
from app.firebase.paths import FirebasePaths


class FirebaseClient:

    def __init__(self):

        self.app = None

    def connect(self):

        if firebase_admin._apps:
            self.app = firebase_admin.get_app()
            return self.app

        credentials_path = (
            Path(__file__).resolve().parents[2]
            / config.FIREBASE_CREDENTIALS
        )

        if not credentials_path.exists():
            raise FileNotFoundError(
                f"Arquivo de credenciais não encontrado:\n"
                f"{credentials_path}"
            )

        cred = credentials.Certificate(credentials_path)

        self.app = firebase_admin.initialize_app(
            cred,
            {
                "databaseURL": config.FIREBASE_DATABASE_URL
            },
        )

        return self.app

    def reference(self, path: str):

        if self.app is None:
            self.connect()

        return db.reference(path)

    def sensors(self):
        """
        Retorna a referência para /sensores
        """

        return self.reference(FirebasePaths.SENSORS)

    def buoys(self):
        """
        Retorna a referência para /boias
        """

        return self.reference(FirebasePaths.BUOYS)

    def sensor_data(self, sensor_id: str):
        """
        Retorna /sensores/{sensor_id}/dados
        """

        return self.reference(
            f"{FirebasePaths.SENSORS}/{sensor_id}/{FirebasePaths.DATA}"
        )

    def buoy_data(self, buoy_id: str):
        """
        Retorna /boias/{buoy_id}/dados
        """

        return self.reference(
            f"{FirebasePaths.BUOYS}/{buoy_id}/{FirebasePaths.DATA}"
        )