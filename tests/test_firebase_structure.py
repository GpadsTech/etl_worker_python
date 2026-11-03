import firebase_admin
from firebase_admin import credentials, db

from app.config.config import config


def test_firebase_structure():

    cred = credentials.Certificate(config.FIREBASE_CREDENTIALS)

    app = firebase_admin.initialize_app(
        cred,
        {
            "databaseURL": config.FIREBASE_DATABASE_URL
        }
    )

    try:
        ref = db.reference("/")
        data = ref.get()

        print("\n" + "=" * 70)
        print("ESTRUTURA DO FIREBASE")
        print("=" * 70)

        if not isinstance(data, dict):
            print(f"Raiz: {type(data).__name__}")
            return

        # =========================================================
        # SENSORES
        # =========================================================

        print("\n" + "-" * 70)
        print("SENSORES - 3 REGISTROS MAIS RECENTES")
        print("-" * 70)

        sensores = data.get("sensores")

        if not isinstance(sensores, dict):
            print("Nenhum dado de sensores encontrado.")

        else:
            registros_sensores = []

            for sensor_id, dados_sensor in sensores.items():

                if not isinstance(dados_sensor, dict):
                    continue

                dados = dados_sensor.get("dados")

                if not isinstance(dados, dict):
                    continue

                for firebase_id, registro in dados.items():

                    if not isinstance(registro, dict):
                        continue

                    timestamp = registro.get("timestamp")

                    registros_sensores.append(
                        (
                            timestamp,
                            sensor_id,
                            firebase_id,
                            registro
                        )
                    )

            # Ordena pelo timestamp, do mais recente para o mais antigo
            registros_sensores.sort(
                key=lambda x: x[0] or "",
                reverse=True
            )

            for timestamp, sensor_id, firebase_id, registro in registros_sensores[:3]:

                print(f"\nSensor: {sensor_id}")
                print(f"Firebase ID: {firebase_id}")

                for campo, valor in registro.items():
                    print(f"  {campo}: {valor}")

        # =========================================================
        # BOIAS
        # =========================================================

        print("\n" + "-" * 70)
        print("BOIAS - 3 REGISTROS MAIS RECENTES")
        print("-" * 70)

        boias = data.get("boias")

        if not isinstance(boias, dict):
            print("Nenhum dado de boias encontrado.")

        else:
            registros_boias = []

            for buoy_id, dados_buoy in boias.items():

                if not isinstance(dados_buoy, dict):
                    continue

                dados = dados_buoy.get("dados")

                if not isinstance(dados, dict):
                    continue

                for firebase_id, registro in dados.items():

                    if not isinstance(registro, dict):
                        continue

                    timestamp = registro.get("timestamp")

                    registros_boias.append(
                        (
                            timestamp,
                            buoy_id,
                            firebase_id,
                            registro
                        )
                    )

            # Ordena pelo timestamp, do mais recente para o mais antigo
            registros_boias.sort(
                key=lambda x: x[0] or "",
                reverse=True
            )

            for timestamp, buoy_id, firebase_id, registro in registros_boias[:3]:

                print(f"\nBoia: {buoy_id}")
                print(f"Firebase ID: {firebase_id}")

                for campo, valor in registro.items():
                    print(f"  {campo}: {valor}")

        print("\n" + "=" * 70)
        print("INSPEÇÃO CONCLUÍDA")
        print("=" * 70)

    finally:
        firebase_admin.delete_app(app)

