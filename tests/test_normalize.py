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

            "Temperatura": 24.21,
            "Umidade": 78.26,
            "Pressao": 1009.37,
            "Hora": "2026-04-23 14:48:35"

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


    def test_normalize_buoy(self):

        firebase = {

            "ADC": "24",
            "Data": "22/07/2026",
            "Hora": "18:27:46",
            "Ph": "7.20",
            "Sensor UV(V)": "2.54",
            "Tensão(V)": "0.81",
            "Turbidez(V)": "3.08"

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


    def test_normalize_buoy_numeric_conversion(self):

        firebase = {

            "ADC": "24",
            "Data": "22/07/2026",
            "Hora": "18:27:46",
            "Ph": "7.20",
            "Sensor UV(V)": "2.54",
            "Tensão(V)": "0.81",
            "Turbidez(V)": "3.08"

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


if __name__ == "__main__":
    unittest.main()
