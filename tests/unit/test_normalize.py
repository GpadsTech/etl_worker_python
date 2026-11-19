"""
Testes do normalize.py
"""

import unittest
from datetime import datetime
from app.transformer.timestamp import SOURCE_TIMEZONE

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
            datetime(2026, 4, 23, 14, 48, 35, tzinfo=SOURCE_TIMEZONE)
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
            datetime(2026, 7, 22, 18, 27, 46, tzinfo=SOURCE_TIMEZONE)
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

    def test_normalize_sensor_converts_numeric_strings(self):

        firebase = {

            "ar": "7.35",
            "chuva": "0",
            "gas": "3.87",
            "hora": "2026-04-23 14:48:35",
            "luz": "701.67",
            "pressao": "1011.75",
            "rpm": "0",
            "temperatura": "27.69",
            "umidade": "52.15",
            "vento": "0",
            "volt": "0.87"

        }

        sensor = normalize_sensor(

            firebase_id="-strings",

            sensor_id="EST002",

            data=firebase,

        )

        for field in (
            "ar",
            "chuva",
            "gas",
            "luz",
            "pressao",
            "rpm",
            "temperatura",
            "umidade",
            "vento",
            "volt",
        ):
            self.assertIsInstance(getattr(sensor, field), float)

        self.assertEqual(sensor.ar, 7.35)
        self.assertEqual(sensor.chuva, 0.0)
        self.assertEqual(sensor.temperatura, 27.69)
        self.assertEqual(sensor.umidade, 52.15)
        self.assertEqual(sensor.volt, 0.87)

    def test_normalize_sensor_empty_and_missing_values_become_none(self):

        firebase = {

            "hora": "2026-04-23 14:48:35",
            "temperatura": "",
            "umidade": "   ",
            "pressao": None

        }

        sensor = normalize_sensor(

            firebase_id="-empty",

            sensor_id="EST002",

            data=firebase,

        )

        self.assertIsNone(sensor.temperatura)
        self.assertIsNone(sensor.umidade)
        self.assertIsNone(sensor.pressao)
        self.assertIsNone(sensor.ar)

    def test_normalize_sensor_rejects_invalid_number(self):

        with self.assertRaises(ValueError) as context:

            normalize_sensor(

                firebase_id="-invalid",

                sensor_id="EST002",

                data={
                    "hora": "2026-04-23 14:48:35",
                    "temperatura": "28,5"
                },

            )

        self.assertIn("temperatura", str(context.exception))

    def test_normalize_sensor_rejects_non_finite_values(self):

        for raw in ("nan", "inf", "-inf"):

            with self.assertRaises(ValueError):

                normalize_sensor(

                    firebase_id="-non-finite",

                    sensor_id="EST002",

                    data={
                        "hora": "2026-04-23 14:48:35",
                        "pressao": raw
                    },

                )

    def test_normalize_sensor_rejects_boolean(self):

        with self.assertRaises(ValueError) as context:

            normalize_sensor(

                firebase_id="-boolean",

                sensor_id="EST002",

                data={
                    "hora": "2026-04-23 14:48:35",
                    "luz": True
                },

            )

        self.assertIn("luz", str(context.exception))

    def test_normalize_sensor_rejects_negative_values(self):

        for field in ("umidade", "rpm", "pressao"):

            with self.assertRaises(ValueError):

                normalize_sensor(

                    firebase_id="-negative",

                    sensor_id="EST002",

                    data={
                        "hora": "2026-04-23 14:48:35",
                        field: -1
                    },

                )

    def test_normalize_sensor_rejects_humidity_above_100(self):

        with self.assertRaises(ValueError) as context:

            normalize_sensor(

                firebase_id="-humidity",

                sensor_id="EST002",

                data={
                    "hora": "2026-04-23 14:48:35",
                    "umidade": 100.1
                },

            )

        self.assertIn("umidade", str(context.exception))

    def test_normalize_sensor_allows_negative_temperature(self):

        sensor = normalize_sensor(

            firebase_id="-cold",

            sensor_id="EST002",

            data={
                "hora": "2026-04-23 14:48:35",
                "temperatura": -5.2
            },

        )

        self.assertEqual(sensor.temperatura, -5.2)

    def test_normalize_buoy_rejects_invalid_number(self):

        with self.assertRaises(ValueError) as context:

            normalize_buoy(

                firebase_id="-invalid",

                buoy_id="BOIA001",

                data={
                    "hora": "2026-06-01 11:04:27",
                    "ph": "22,84"
                },

            )

        self.assertIn("ph", str(context.exception))


if __name__ == "__main__":
    unittest.main()
