"""
Testes do normalize.py
"""

import unittest
from datetime import datetime

from app.transformer.normalize import (
    normalize_sensor,
    normalize_buoy,
)

from app.models.sensor import Sensor
from app.models.buoy import Buoy


class TestNormalize(unittest.TestCase):

    def test_normalize_sensor(self):

        firebase = {

            "temperatura": 24.21,
            "umidade": 78.26,
            "pressao": 1009.37,
            "hora": "2026-04-23 14:48:35"

        }

        sensor = normalize_sensor(

            firebase_id="-abc123",

            sensor_id="EST001",

            data=firebase,

        )

        self.assertIsInstance(sensor, Sensor)

        self.assertEqual(sensor.firebase_id, "-abc123")

        self.assertEqual(sensor.sensor_id, "EST001")

        self.assertEqual(sensor.temperatura, 24.21)

        self.assertEqual(sensor.umidade, 78.26)

        self.assertEqual(sensor.pressao, 1009.37)

        self.assertIsInstance(sensor.timestamp, datetime)

        self.assertEqual(
            sensor.timestamp,
            datetime(2026, 4, 23, 14, 48, 35)
        )

    def test_normalize_sensor_discards_metadata(self):

        firebase = {

            "temperatura": 24.21,
            "hora": "2026-04-23 14:48:35",
            "endereco_ip": "192.168.0.10",
            "identificador": 7

        }

        sensor = normalize_sensor(

            firebase_id="-abc123",

            sensor_id="EST001",

            data=firebase,

        )

        self.assertFalse(hasattr(sensor, "endereco_ip"))

        self.assertFalse(hasattr(sensor, "identificador"))

    def test_normalize_buoy(self):

        firebase = {

            "adc": "24",
            "hora": "2026-07-22 18:27:46",
            "ph": "7.20",
            "sensor_uv_v": "2.54",
            "tensao_v": "0.81",
            "turbidez_v": "3.08"

        }

        buoy = normalize_buoy(

            firebase_id="-xyz456",

            buoy_id="BOIA001",

            data=firebase,

        )

        self.assertIsInstance(buoy, Buoy)

        self.assertEqual(buoy.firebase_id, "-xyz456")

        self.assertEqual(buoy.buoy_id, "BOIA001")

        self.assertEqual(buoy.adc, 24.0)

        self.assertEqual(buoy.ph, 7.20)

        self.assertEqual(buoy.sensor_uv_v, 2.54)

        self.assertEqual(buoy.tensao_v, 0.81)

        self.assertEqual(buoy.turbidez_v, 3.08)

        self.assertIsInstance(buoy.timestamp, datetime)

        self.assertEqual(
            buoy.timestamp,
            datetime(2026, 7, 22, 18, 27, 46)
        )

    def test_normalize_buoy_without_adc(self):

        firebase = {

            "hora": "2026-06-01 11:04:27",
            "ph": 22.84,
            "sensor_uv_v": 3.3,
            "turbidez_v": 3.3

        }

        buoy = normalize_buoy(

            firebase_id="-sem-adc",

            buoy_id="BOIA002",

            data=firebase,

        )

        self.assertIsNone(buoy.adc)

        self.assertIsNone(buoy.tensao_v)

    def test_normalize_buoy_numeric_conversion(self):

        firebase = {

            "adc": "24",
            "hora": "2026-07-22 18:27:46",
            "ph": "7.20",
            "sensor_uv_v": "2.54",
            "tensao_v": "0.81",
            "turbidez_v": "3.08"

        }

        buoy = normalize_buoy(

            firebase_id="-conversion-test",

            buoy_id="BOIA001",

            data=firebase,

        )

        self.assertIsInstance(buoy.adc, float)
        self.assertIsInstance(buoy.ph, float)
        self.assertIsInstance(buoy.sensor_uv_v, float)
        self.assertIsInstance(buoy.tensao_v, float)
        self.assertIsInstance(buoy.turbidez_v, float)

        self.assertEqual(buoy.adc, 24.0)
        self.assertEqual(buoy.ph, 7.20)
        self.assertEqual(buoy.sensor_uv_v, 2.54)
        self.assertEqual(buoy.tensao_v, 0.81)
        self.assertEqual(buoy.turbidez_v, 3.08)

    def test_normalize_buoy_empty_numeric_values(self):

        firebase = {

            "adc": "",
            "hora": "2026-07-22 18:27:46",
            "ph": " ",
            "sensor_uv_v": None,
            "turbidez_v": "3.08"

        }

        buoy = normalize_buoy(

            firebase_id="-empty-values",

            buoy_id="BOIA001",

            data=firebase,

        )

        self.assertIsNone(buoy.adc)
        self.assertIsNone(buoy.ph)
        self.assertIsNone(buoy.sensor_uv_v)
        self.assertEqual(buoy.turbidez_v, 3.08)


if __name__ == "__main__":
    unittest.main()
