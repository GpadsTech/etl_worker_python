"""
Importa todos os registros existentes
do Firebase para o TimescaleDB.
"""

from app.firebase.client import FirebaseClient

from app.transformer.normalize import (
    normalize_sensor,
    normalize_buoy,
)

from app.database.sensor_repository import SensorRepository
from app.database.buoy_repository import BuoyRepository


class BootstrapReader:

    def __init__(self):

        self.client = FirebaseClient()

        self.sensor_repository = SensorRepository()

        self.buoy_repository = BuoyRepository()

    def run(self):

        self.import_sensors()

        self.import_buoys()

    def import_sensors(self):

        sensors = self.client.sensors().get()

        if not sensors:
            return

        for sensor_id, sensor_data in sensors.items():

            registros = sensor_data.get("dados", {})

            for firebase_id, registro in registros.items():

                sensor = normalize_sensor(

                    firebase_id=firebase_id,

                    sensor_id=sensor_id,

                    data=registro,

                )

                self.sensor_repository.insert(sensor)

        print("Sensores importados.")

    def import_buoys(self):

        buoys = self.client.buoys().get()

        if not buoys:
            return

        for buoy_id, buoy_data in buoys.items():

            registros = buoy_data.get("dados", {})

            for firebase_id, registro in registros.items():

                buoy = normalize_buoy(

                    firebase_id=firebase_id,

                    buoy_id=buoy_id,

                    data=registro,

                )

                self.buoy_repository.insert(buoy)

        print("Boias importadas.")
