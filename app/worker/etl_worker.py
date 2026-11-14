"""
Orquestrador do processo ETL.

Responsável por:

- Ler dados do Firebase de forma incremental (checkpoint por equipamento)
- Normalizar os registros
- Persistir os dados no TimescaleDB em lote
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
from app.repository.checkpoint_repository import CheckpointRepository
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

        self.checkpoints = CheckpointRepository(
            self.database
        )

        self.logger = get_logger()

    def _process(
        self,
        source: str,
        root_reference,
        data_reference,
        normalize,
        id_field: str,
        repository,
    ) -> tuple[int, int, int, int]:
        """
        Processa uma origem (sensores ou boias) de forma incremental.

        Para cada equipamento, lê apenas as chaves posteriores ao último
        checkpoint, normaliza os registros e grava em lote. O checkpoint
        só avança depois do commit dos dados; se a gravação falhar, os
        registros são lidos novamente no próximo ciclo.
        """

        self.firebase.connect()

        equipamentos = root_reference.get(shallow=True)

        if not isinstance(equipamentos, dict):
            return 0, 0, 0, 0

        recebidos = 0
        inseridos = 0
        ignorados = 0
        erros = 0

        for device_id in sorted(equipamentos):

            ultima_chave = self.checkpoints.get(source, device_id)

            consulta = data_reference(device_id).order_by_key()

            if ultima_chave is not None:
                # start_at é inclusivo: o registro de fronteira é pulado
                # pelo filtro abaixo.
                consulta = consulta.start_at(ultima_chave)

            registros = consulta.get()

            if not isinstance(registros, dict):
                continue

            pendentes = []
            maior_chave = ultima_chave

            for firebase_id, data in registros.items():

                if not isinstance(data, dict):
                    continue

                if (
                    ultima_chave is not None
                    and firebase_id <= ultima_chave
                ):
                    continue

                recebidos += 1

                if maior_chave is None or firebase_id > maior_chave:
                    maior_chave = firebase_id

                try:
                    pendentes.append(
                        normalize(
                            firebase_id=firebase_id,
                            **{id_field: device_id},
                            data=data,
                        )
                    )

                except Exception as error:
                    erros += 1

                    self.logger.error(
                        f"Falha ao normalizar {source} | "
                        f"Equipamento: {device_id} | "
                        f"Firebase ID: {firebase_id} | "
                        f"Motivo: {error}"
                    )

            falhou_banco = False

            if pendentes:

                try:
                    criados = repository.insert_many(pendentes)

                    inseridos += criados
                    ignorados += len(pendentes) - criados

                except Exception as error:
                    erros += len(pendentes)
                    falhou_banco = True

                    self.logger.error(
                        f"Falha ao gravar {source} | "
                        f"Equipamento: {device_id} | "
                        f"Registros: {len(pendentes)} | "
                        f"Motivo: {error}"
                    )

            if (
                maior_chave is not None
                and maior_chave != ultima_chave
                and not falhou_banco
            ):
                try:
                    self.checkpoints.set(
                        source,
                        device_id,
                        maior_chave,
                    )

                except Exception as error:
                    # Os dados já foram commitados. Repetir a leitura no
                    # próximo ciclo é seguro: ON CONFLICT DO NOTHING evita
                    # duplicação.
                    self.logger.error(
                        f"Falha ao gravar checkpoint | "
                        f"Origem: {source} | "
                        f"Equipamento: {device_id} | "
                        f"Motivo: {error}"
                    )

        return recebidos, inseridos, ignorados, erros

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

        return self._process(
            source="sensores",
            root_reference=self.firebase.sensors(),
            data_reference=self.firebase.sensor_data,
            normalize=normalize_sensor,
            id_field="sensor_id",
            repository=self.sensor_repository,
        )

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

        return self._process(
            source="boias",
            root_reference=self.firebase.buoys(),
            data_reference=self.firebase.buoy_data,
            normalize=normalize_buoy,
            id_field="buoy_id",
            repository=self.buoy_repository,
        )

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
