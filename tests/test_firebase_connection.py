import firebase_admin
from firebase_admin import credentials, db

from app.config.config import config


def test_firebase_connection():
    cred = credentials.Certificate(config.FIREBASE_CREDENTIALS)

    app = firebase_admin.initialize_app(
        cred,
        {
            "databaseURL": config.FIREBASE_DATABASE_URL
        }
    )

    ref = db.reference("/")
    data = ref.get()

    print("\nFirebase conectado com sucesso.")
    print("Tipo de dado recebido:", type(data).__name__)

    firebase_admin.delete_app(app)