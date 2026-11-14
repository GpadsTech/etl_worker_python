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
        self.assertEqual(ts.hour, 14)
        self.assertEqual(ts.minute, 48)
        self.assertEqual(ts.second, 35)

    def test_buoy_timestamp_uses_single_full_datetime(self):

        ts = buoy_timestamp(
            "2026-06-01 11:04:27"
        )

        self.assertIsInstance(ts, datetime)

        self.assertEqual(ts.year, 2026)
        self.assertEqual(ts.month, 6)
        self.assertEqual(ts.day, 1)
        self.assertEqual(ts.hour, 11)
        self.assertEqual(ts.minute, 4)
        self.assertEqual(ts.second, 27)

    def test_buoy_timestamp_rejects_legacy_split_format(self):

        with self.assertRaises(ValueError):
            buoy_timestamp("22/07/2026 18:27:46")


if __name__ == "__main__":
    unittest.main()
