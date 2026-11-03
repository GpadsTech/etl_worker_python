"""
Testes do timestamp.py
"""

import unittest
from datetime import datetime

from app.transformer.timestamp import (
    sensor_timestamp,
    buoy_timestamp,
)


class TestTimestamp(unittest.TestCase):

    def test_sensor_timestamp(self):

        ts = sensor_timestamp(
            "2026-04-23 14:48:35"
        )

        self.assertIsInstance(ts, datetime)

        self.assertEqual(ts.year, 2026)
        self.assertEqual(ts.month, 4)
        self.assertEqual(ts.day, 23)

    def test_buoy_timestamp(self):

        ts = buoy_timestamp(
            "22/07/2026",
            "18:27:46"
        )

        self.assertIsInstance(ts, datetime)

        self.assertEqual(ts.year, 2026)
        self.assertEqual(ts.month, 7)
        self.assertEqual(ts.day, 22)


if __name__ == "__main__":
    unittest.main()