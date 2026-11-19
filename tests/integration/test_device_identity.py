"""Contrato SQL de identidade para sensores e boias, somente em tabelas TEMP."""

from datetime import datetime

from app.models.buoy import Buoy
from app.models.sensor import Sensor
from app.repository.buoy_repository import BuoyRepository
from app.repository.sensor_repository import SensorRepository
from app.transformer.timestamp import SOURCE_TIMEZONE
from tests.integration.gate import integration_test
from tests.integration.temporary_database import TemporaryDatabaseTestCase


@integration_test
class TestDeviceIdentity(TemporaryDatabaseTestCase):
    def test_device_identity_preserves_first_version_for_both_sources(self):
        for model, repository_class, device_column, value_column in (
            (Sensor, SensorRepository, "sensor_id", "temperatura"),
            (Buoy, BuoyRepository, "buoy_id", "ph"),
        ):
            with self.subTest(source=repository_class.table_name):
                repository = repository_class(self.database)
                instant = datetime(2026, 8, 20, tzinfo=SOURCE_TIMEZONE)
                readings = [
                    model("-001", "DEVICE_A", instant, **{value_column: 1}),
                    model("-002", "DEVICE_A", instant, **{value_column: 2}),
                    model("-001", "DEVICE_B", instant, **{value_column: 3}),
                ]
                self.assertEqual(repository.insert_many(readings), 3)
                self.assertEqual(repository.insert_many(readings), 0)
                changed = model(
                    "-001", "DEVICE_A", datetime(2026, 8, 21, tzinfo=SOURCE_TIMEZONE),
                    **{value_column: 99},
                )
                self.assertFalse(repository.insert(changed))
                with self.database.connect().cursor() as cursor:
                    cursor.execute(f"""
                        SELECT timestamp, {value_column}
                        FROM pg_temp.{repository.table_name}
                        WHERE {device_column} = %s AND firebase_id = %s
                    """, ("DEVICE_A", "-001"))
                    self.assertEqual(cursor.fetchall(), [(instant, 1)])
                    cursor.execute(f"SELECT count(*) FROM pg_temp.{repository.table_name}")
                    self.assertEqual(cursor.fetchone()[0], 3)
