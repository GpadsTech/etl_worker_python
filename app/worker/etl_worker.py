"""
Orquestrador do processo ETL.

Responsável por:

- Ler dados do Firebase de forma incremental (checkpoint por equipamento)
- Normalizar os registros
- Persistir os dados no PostgreSQL em lote
- Tratar erros individuais sem interromper o processamento
"""
from functools import wraps

from psycopg2 import DataError, IntegrityError

from app.utils.logger import get_logger
from app.firebase.client import FirebaseClient
from app.transformer.normalize import (
    normalize_sensor,
    normalize_buoy,
)
from app.repository.sensor_repository import SensorRepository
from app.repository.buoy_repository import BuoyRepository
from app.repository.checkpoint_repository import CheckpointRepository
from app.repository.rejection_repository import RejectionRepository
from app.models.rejection import Rejection
from app.database.connection import DatabaseConnection, WorkerLockLostError


def exclusive_operation(method):
    """Protege também chamadas diretas, não somente o loop de main."""
    @wraps(method)
    def protected(self, *args, **kwargs):
        with self.database.exclusive():
            return method(self, *args, **kwargs)
    return protected


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

        self.rejections = RejectionRepository(
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
        avança mesmo com leituras inválidas, depois de salvar os válidos e
        as rejeições. Somente falhas operacionais que impeçam persistência
        deixam o checkpoint anterior para permitir uma nova tentativa.
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
            rejeitados = []
            maior_chave = ultima_chave

            for firebase_id, data in registros.items():

                if (
                    ultima_chave is not None
                    and firebase_id <= ultima_chave
                ):
                    continue

                recebidos += 1

                if maior_chave is None or firebase_id > maior_chave:
                    maior_chave = firebase_id

                try:
                    if not isinstance(data, dict):
                        raise ValueError("A leitura deve ser um objeto JSON.")

                    pendentes.append(
                        normalize(
                            firebase_id=firebase_id,
                            **{id_field: device_id},
                            data=data,
                        )
                    )

                except WorkerLockLostError:
                    raise
                except Exception as error:
                    erros += 1
                    rejeitados.append(
                        Rejection(
                            source, device_id, firebase_id, data,
                            f"{type(error).__name__}: {error}",
                        )
                    )

                    self.logger.error(
                        f"Falha ao normalizar {source} | "
                        f"Equipamento: {device_id} | "
                        f"Firebase ID: {firebase_id} | "
                        f"Tipo: {type(error).__name__}"
                    )

            falhou_banco = False

            if pendentes:

                try:
                    criados = repository.insert_many(pendentes)

                    inseridos += criados
                    ignorados += len(pendentes) - criados

                except (DataError, IntegrityError):
                    # O repository já reverteu todo o lote. Isolar erros
                    # de dados para que uma leitura não descarte as demais.
                    criados, existentes, falhas, rejeicoes_sql = (
                        self._persist_individually(
                            repository, pendentes, registros, source, device_id,
                        )
                    )
                    inseridos += criados
                    ignorados += existentes
                    erros += falhas + len(rejeicoes_sql)
                    rejeitados.extend(rejeicoes_sql)
                    falhou_banco = falhas > 0

                except WorkerLockLostError:
                    raise
                except Exception as error:
                    erros += len(pendentes)
                    falhou_banco = True

                    self.logger.error(
                        f"Falha ao gravar {source} | "
                        f"Equipamento: {device_id} | "
                        f"Registros: {len(pendentes)} | "
                        f"Tipo: {type(error).__name__}"
                    )

            # A classificação de todo o equipamento terminou. Rejeições
            # são um resultado durável do ETL, não uma fila que bloqueia
            # o avanço à espera de correção ou ação manual.
            if rejeitados:
                try:
                    self.rejections.save_many(rejeitados)
                except WorkerLockLostError:
                    raise
                except Exception as error:
                    falhou_banco = True
                    self.logger.error(
                        f"Falha ao salvar rejeições de {source} | "
                        f"Equipamento: {device_id} | "
                        f"Registros: {len(rejeitados)} | "
                        f"Tipo: {type(error).__name__}"
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

                except WorkerLockLostError:
                    raise
                except Exception as error:
                    # Dados e rejeições já foram commitados. Repetir a
                    # leitura é seguro: suas chaves evitam duplicação.
                    self.logger.error(
                        f"Falha ao gravar checkpoint | "
                        f"Origem: {source} | "
                        f"Equipamento: {device_id} | "
                        f"Motivo: {error}"
                    )

        return recebidos, inseridos, ignorados, erros

    def _persist_individually(
        self, repository, objects, payloads, source, device_id,
    ) -> tuple[int, int, int, list[Rejection]]:
        """Fallback após rollback de lote com erro SQL de dados/integridade.

        Falha operacional não é categorizada como dado inválido: sem
        persistência confirmada, a leitura precisa continuar recuperável.
        """
        inserted = existing = failures = 0
        rejected = []
        for obj in objects:
            try:
                if repository.insert(obj):
                    inserted += 1
                else:
                    existing += 1
            except (DataError, IntegrityError) as error:
                rejected.append(
                    Rejection(
                        source, device_id, obj.firebase_id,
                        payloads[obj.firebase_id],
                        f"Persistência | {type(error).__name__}: {error}",
                    )
                )
                self.logger.error(
                    f"Leitura rejeitada na persistência de {source} | "
                    f"Equipamento: {device_id} | "
                    f"Firebase ID: {obj.firebase_id} | "
                    f"Tipo: {type(error).__name__}"
                )
            except WorkerLockLostError:
                raise
            except Exception as error:
                failures += 1
                self.logger.error(
                    f"Falha operacional ao gravar {source} | "
                    f"Equipamento: {device_id} | "
                    f"Firebase ID: {obj.firebase_id} | "
                    f"Tipo: {type(error).__name__}"
                )
        return inserted, existing, failures, rejected

    @exclusive_operation
    def reprocess_rejections(
        self,
        limit: int = 100,
        source: str | None = None,
        device_id: str | None = None,
        refresh_from_firebase: bool = False,
    ) -> tuple[int, int, int, int]:
        """Retorna (tentados, inseridos, existentes, erros), sem mover checkpoints.

        Por padrão usa o payload salvo (ex.: após corrigir o normalizador).
        A releitura opcional do Firebase permite recuperar registros corrigidos
        na origem, mantendo o payload rejeitado original para diagnóstico.
        O commit da medição precede a resolução; interrupções permitem replay.
        """
        pending = self.rejections.pending(limit, source, device_id)
        inserted = existing = errors = 0

        for rejection in pending:
            try:
                if rejection.source == "sensores":
                    normalize = normalize_sensor
                    id_field = "sensor_id"
                    repository = self.sensor_repository
                    data_reference = self.firebase.sensor_data
                elif rejection.source == "boias":
                    normalize = normalize_buoy
                    id_field = "buoy_id"
                    repository = self.buoy_repository
                    data_reference = self.firebase.buoy_data
                else:
                    raise ValueError("Origem inválida.")

                payload = rejection.payload
                if refresh_from_firebase:
                    payload = data_reference(rejection.device_id).child(
                        rejection.firebase_id
                    ).get()

                if not isinstance(payload, dict):
                    raise ValueError("Leitura ausente ou não é um objeto JSON.")

                obj = normalize(
                    firebase_id=rejection.firebase_id,
                    **{id_field: rejection.device_id},
                    data=payload,
                )
                created = repository.insert(obj)
            except WorkerLockLostError:
                raise
            except Exception as error:
                errors += 1
                # Se gravar a tentativa falhar, abortar o comando: a rejeição
                # continua pendente e a falha operacional não é escondida.
                self.rejections.mark_failed(
                    rejection, f"{type(error).__name__}: {error}",
                )
                self.logger.error(
                    f"Falha ao reprocessar {rejection.source} | "
                    f"Equipamento: {rejection.device_id} | "
                    f"Firebase ID: {rejection.firebase_id} | "
                    f"Tipo: {type(error).__name__}"
                )
                continue

            # Falha aqui aborta o comando, mantendo replay idempotente.
            self.rejections.mark_resolved(rejection)
            inserted += int(created)
            existing += int(not created)

        return len(pending), inserted, existing, errors

    @exclusive_operation
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

    @exclusive_operation
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

    @exclusive_operation
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
