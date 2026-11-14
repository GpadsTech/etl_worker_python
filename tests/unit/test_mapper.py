"""
Testes do mapper.py
"""

import unittest

from app.transformer.mapper import FieldMapper


class TestFieldMapper(unittest.TestCase):

    def test_sensor_mapper_uses_lowercase_keys(self):

        self.assertEqual(
            FieldMapper.SENSOR["temperatura"],
            "temperatura"
        )

        self.assertEqual(
            FieldMapper.SENSOR["hora"],
            "timestamp"
        )

        self.assertEqual(
            FieldMapper.SENSOR["volt"],
            "volt"
        )

        self.assertEqual(
            FieldMapper.SENSOR["chuva"],
            "chuva"
        )

    def test_buoy_mapper_uses_lowercase_keys(self):

        self.assertEqual(
            FieldMapper.BUOY["adc"],
            "adc"
        )

        self.assertEqual(
            FieldMapper.BUOY["sensor_uv_v"],
            "sensor_uv_v"
        )

        self.assertEqual(
            FieldMapper.BUOY["tensao_v"],
            "tensao_v"
        )

        self.assertEqual(
            FieldMapper.BUOY["hora"],
            "timestamp"
        )

    def test_legacy_capitalized_keys_are_not_mapped(self):

        for key in ("Temperatura", "Hora", "Data", "ADC"):
            self.assertNotIn(key, FieldMapper.SENSOR)
            self.assertNotIn(key, FieldMapper.BUOY)


if __name__ == "__main__":
    unittest.main()
