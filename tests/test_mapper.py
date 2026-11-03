"""
Testes do mapper.py
"""

import unittest

from app.transformer.mapper import FieldMapper


class TestFieldMapper(unittest.TestCase):

    def test_sensor_mapper(self):

        self.assertEqual(
            FieldMapper.SENSOR["Temperatura"],
            "temperatura"
        )

        self.assertEqual(
            FieldMapper.SENSOR["Hora"],
            "timestamp"
        )

        self.assertEqual(
            FieldMapper.SENSOR["Volt"],
            "volt"
        )

    def test_buoy_mapper(self):

        self.assertEqual(
            FieldMapper.BUOY["ADC"],
            "adc"
        )

        self.assertEqual(
            FieldMapper.BUOY["Sensor UV(V)"],
            "sensor_uv_v"
        )

        self.assertEqual(
            FieldMapper.BUOY["Tensão(V)"],
            "tensao_v"
        )


if __name__ == "__main__":
    unittest.main()