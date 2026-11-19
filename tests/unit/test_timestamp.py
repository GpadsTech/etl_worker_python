"""
Testes do timestamp.py
"""

import unittest
from datetime import datetime, timedelta, timezone

from app.transformer.timestamp import (
    sensor_timestamp,
    buoy_timestamp,
)


class TestTimestamp(unittest.TestCase):

    def test_source_timezone_and_historical_summer_time(self):
        for parser in (sensor_timestamp, buoy_timestamp):
            with self.subTest(parser=parser.__name__):
                current = parser("2026-04-23 14:48:35")
                self.assertEqual(current.tzinfo.key, "America/Sao_Paulo")
                self.assertEqual(current.utcoffset(), timedelta(hours=-3))
                self.assertEqual(
                    current.astimezone(timezone.utc),
                    datetime(2026, 4, 23, 17, 48, 35, tzinfo=timezone.utc),
                )
                self.assertEqual(
                    parser("2018-01-15 12:00:00").utcoffset(), timedelta(hours=-2),
                )

    def test_ambiguous_and_nonexistent_times_are_rejected(self):
        for parser in (sensor_timestamp, buoy_timestamp):
            for value, message in (
                ("2018-11-04 00:30:00", "inexistente"),
                ("2018-02-17 23:30:00", "ambígua"),
            ):
                with self.subTest(parser=parser.__name__, value=value):
                    with self.assertRaisesRegex(ValueError, message):
                        parser(value)

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
