"""
Orquestrador do processo ETL.

Responsável por:

- Ler dados do Firebase
- Normalizar os registros
- Persistir os dados no TimescaleDB
- Tratar erros individuais sem interromper o processamento
"""
from app.utils.logger import get_logger
from app.firebase.client import FirebaseClient
from app.transformer.normalize import (
    normalize_sensor,
    normalize_buoy,
)
from app.repository.sensor_repository import SensorRepository
from app.repository.buoy_repository import BuoyRepository
from app.database.connection import DatabaseConnection


class ETLWorker:

    def __init__(self):
        self.firebase = FirebaseClient()
        self.database = DatabaseConnection()

        self.sensor_repository = SensorRepository(
            self.database
        )

        self.buoy_repository = BuoyRepository(
            self.database
        )

        self.logger = get_logger()

    def process_sensors(self) -> tuple[int, int, int, int]:
        """
        Processa os registros dos sensores.

        Retorna:
            (
                recebidos,
                inseridos,
                ignorados,
                erros
            )
        """

        self.firebase.connect()

        sensores = self.firebase.sensors().get()

        if not isinstance(sensores, dict):
            return 0, 0, 0, 0

        recebidos = 0
        inseridos = 0
        ignorados = 0
        erros = 0

        for sensor_id, sensor_data in sensores.items():

            if not isinstance(sensor_data, dict):
                continue

            registros = sensor_data.get("dados")

            if not isinstance(registros, dict):
                continue

            for firebase_id, data in registros.items():

                if not isinstance(data, dict):
                    continue

                recebidos += 1

                try:
                    sensor = normalize_sensor(
                        firebase_id=firebase_id,
                        sensor_id=sensor_id,
                        data=data,
                    )

                    foi_inserido = self.sensor_repository.insert(
                        sensor
                    )

                    if foi_inserido:
                        inseridos += 1
                    else:
                        ignorados += 1

                except Exception as error:
                    erros += 1

                    self.logger.error(
                        f"Falha ao processar sensor | "
                        f"Sensor ID: {sensor_id} | "
                        f"Firebase ID: {firebase_id} | "
                        f"Motivo: {error}"
                    )

        return recebidos, inseridos, ignorados, erros

    def process_buoys(self) -> tuple[int, int, int, int]:
        """
        Processa os registros das boias.

        Retorna:
            (
                recebidos,
                inseridos,
                ignorados,
                erros
            )
        """

        self.firebase.connect()

        boias = self.firebase.buoys().get()

        if not isinstance(boias, dict):
            return 0, 0, 0, 0

        recebidos = 0
        inseridos = 0
        ignorados = 0
        erros = 0

        for buoy_id, buoy_data in boias.items():

            if not isinstance(buoy_data, dict):
                continue

            registros = buoy_data.get("dados")

            if not isinstance(registros, dict):
                continue

            for firebase_id, data in registros.items():

                if not isinstance(data, dict):
                    continue

                recebidos += 1

                try:
                    buoy = normalize_buoy(
                        firebase_id=firebase_id,
                        buoy_id=buoy_id,
                        data=data,
                    )

                    foi_inserido = self.buoy_repository.insert(
                        buoy
                    )

                    if foi_inserido:
                        inseridos += 1
                    else:
                        ignorados += 1

                except Exception as error:
                    erros += 1

                    self.logger.error(
                        f"Falha ao processar boia | "
                        f"Boia ID: {buoy_id} | "
                        f"Firebase ID: {firebase_id} | "
                        f"Motivo: {error}"
                    )

        return recebidos, inseridos, ignorados, erros

    def run_once(self) -> tuple[
        tuple[int, int, int, int],
        tuple[int, int, int, int]
    ]:
        """
        Executa uma rodada completa do ETL.

        Retorna:

            (
                (
                    sensores_recebidos,
                    sensores_inseridos,
                    sensores_ignorados,
                    sensores_erros
                ),
                (
                    boias_recebidas,
                    boias_inseridas,
                    boias_ignoradas,
                    boias_erros
                )
            )
        """

        self.logger.info("=" * 70)
        self.logger.info("INICIANDO ETL")
        self.logger.info("=" * 70)

        sensores = self.process_sensors()

        self.logger.info("SENSORES")
        self.logger.info(f"Recebidos: {sensores[0]}")
        self.logger.info(f"Inseridos: {sensores[1]}")
        self.logger.info(f"Já existentes: {sensores[2]}")
        self.logger.info(f"Erros: {sensores[3]}")

        boias = self.process_buoys()

        self.logger.info("BOIAS")
        self.logger.info(f"Recebidos: {boias[0]}")
        self.logger.info(f"Inseridos: {boias[1]}")
        self.logger.info(f"Já existentes: {boias[2]}")
        self.logger.info(f"Erros: {boias[3]}")

        #self.database.close()

        self.logger.info("=" * 70)
        self.logger.info("ETL FINALIZADO")
        self.logger.info("=" * 70)

        return sensores, boias