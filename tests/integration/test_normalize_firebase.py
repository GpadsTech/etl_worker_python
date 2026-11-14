"""
Teste de normalização usando dados reais do Firebase.

Fluxo testado:

Firebase
    ↓
FirebaseClient
    ↓
registro real
    ↓
normalize_sensor / normalize_buoy
    ↓
Sensor / Buoy
"""

import unittest
from tests.integration.gate import integration_test

from app.firebase.client import FirebaseClient
from app.transformer.normalize import (
    normalize_sensor,
    normalize_buoy,
)

from app.models.sensor import Sensor
from app.models.buoy import Buoy


@integration_test
class TestNormalizeFirebase(unittest.TestCase):

    def test_normalize_sensor_real(self):

        client = FirebaseClient()

        # Conecta ao Firebase
        client.connect()

        # Obtém os dados do sensor EST001
        ref = client.sensor_data("EST001")
        data = ref.get()

        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 0)

        # Pega o último registro
        firebase_id, firebase_data = list(data.items())[-1]

        print("\n" + "=" * 70)
        print("NORMALIZAÇÃO - SENSOR REAL")
        print("=" * 70)

        sensor_id = "EST001"

        print(f"Sensor ID: {sensor_id}")
        print(f"Firebase ID: {firebase_id}")

        # Normaliza o registro
        sensor = normalize_sensor(
            firebase_id=firebase_id,
            sensor_id=sensor_id,
            data=firebase_data,
        )

        # Valida o resultado
        self.assertIsInstance(sensor, Sensor)

        print("\nObjeto Sensor:")
        print(sensor)

        print("\nTipos dos campos:")

        print(
            f"  temperatura: "
            f"{sensor.temperatura} "
            f"({type(sensor.temperatura).__name__})"
        )

        print(
            f"  umidade: "
            f"{sensor.umidade} "
            f"({type(sensor.umidade).__name__})"
        )

        print(
            f"  pressao: "
            f"{sensor.pressao} "
            f"({type(sensor.pressao).__name__})"
        )

        print(
            f"  timestamp: "
            f"{sensor.timestamp} "
            f"({type(sensor.timestamp).__name__})"
        )

    def test_normalize_buoy_real(self):

        client = FirebaseClient()

        # Conecta ao Firebase
        client.connect()

        # Obtém os dados da boia BOIA001
        ref = client.buoy_data("BOIA001")
        data = ref.get()

        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 0)

        # Pega o último registro
        firebase_id, firebase_data = list(data.items())[-1]

        print("\n" + "=" * 70)
        print("NORMALIZAÇÃO - BOIA REAL")
        print("=" * 70)

        print(f"Boia ID: {'BOIA001'}")
        print(f"Firebase ID: {firebase_id}")

        # Normaliza o registro
        buoy = normalize_buoy(
            firebase_id=firebase_id,
            buoy_id="BOIA001",
            data=firebase_data,
        )

        # Valida o resultado
        self.assertIsInstance(buoy, Buoy)

        print("\nObjeto Buoy:")
        print(buoy)

        print("\nTipos dos campos:")

        print(
            f"  adc: "
            f"{buoy.adc} "
            f"({type(buoy.adc).__name__})"
        )

        print(
            f"  ph: "
            f"{buoy.ph} "
            f"({type(buoy.ph).__name__})"
        )

        print(
            f"  sensor_uv_v: "
            f"{buoy.sensor_uv_v} "
            f"({type(buoy.sensor_uv_v).__name__})"
        )

        print(
            f"  tensao_v: "
            f"{buoy.tensao_v} "
            f"({type(buoy.tensao_v).__name__})"
        )

        print(
            f"  turbidez_v: "
            f"{buoy.turbidez_v} "
            f"({type(buoy.turbidez_v).__name__})"
        )

        print(
            f"  timestamp: "
            f"{buoy.timestamp} "
            f"({type(buoy.timestamp).__name__})"
        )


if __name__ == "__main__":
    unittest.main()
