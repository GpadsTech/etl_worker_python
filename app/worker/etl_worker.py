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
from app.firebase.pagination import iter_pages, last_key, window_start, validate_key
from app.config.config import config
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
        self.page_size = config.ETL_PAGE_SIZE
        self.lookback_records = config.ETL_LOOKBACK_RECORDS

    def _process(
        self,
        source: str,
        root_reference,
        data_reference,
        normalize,
        id_field: str,
        repository,
    ) -> tuple[int, int, int, int]:
        """Reconsulta limitada seguida de avanço até um horizonte fixo."""
        self.firebase.connect()
        equipamentos = root_reference.get(shallow=True)
        if equipamentos is None:
            return 0, 0, 0, 0
        if not isinstance(equipamentos, dict):
            raise ValueError("Raiz Firebase deve ser um objeto.")
        totals = [0, 0, 0, 0]
        for device_id in sorted(equipamentos):
            checkpoint = self.checkpoints.get(source, device_id)
            if checkpoint is not None:
                validate_key(checkpoint)
            reference = data_reference(device_id)
            horizon = last_key(reference)
            if horizon is None:
                continue
            durable = True
            if checkpoint is not None and self.lookback_records:
                lower = window_start(
                    reference, checkpoint, self.lookback_records, self.page_size,
                )
                if lower is not None:
                    for page in iter_pages(
                        reference, self.page_size, start=lower, end=min(checkpoint, horizon),
                    ):
                        counts, durable = self._persist_unseen(
                            source, device_id, page, normalize, id_field, repository,
                        )
                        totals = [a + b for a, b in zip(totals, counts)]
                        if not durable:
                            break
            if not durable:
                continue
            for page in iter_pages(reference, self.page_size, after=checkpoint, end=horizon):
                counts, durable = self._persist_page(
                    source, device_id, page, normalize, id_field, repository,
                )
                totals = [a + b for a, b in zip(totals, counts)]
                if not durable:
                    break
                try:
                    self.checkpoints.set(source, device_id, max(page))
                except WorkerLockLostError:
                    raise
                except Exception as error:
                    self.logger.error(
                        f"Falha ao gravar checkpoint | Origem: {source} | "
                        f"Equipamento: {device_id} | Tipo: {type(error).__name__}"
                    )
                    break
        return tuple(totals)

    def _persist_unseen(self, source, device_id, page, normalize, id_field, repository):
        known = repository.existing_ids(device_id, page)
        known |= self.rejections.existing_ids(source, device_id, page)
        unseen = {key: value for key, value in page.items() if key not in known}
        return self._persist_page(source, device_id, unseen, normalize, id_field, repository)

    def _persist_page(self, source, device_id, registros, normalize, id_field, repository):
        """Retorna contagens e confirmação de durabilidade; nunca move cursor."""
        recebidos = 0
        inseridos = 0
        ignorados = 0
        erros = 0

        pendentes, rejeitados = [], []
        for firebase_id, data in registros.items():
            recebidos += 1
            try:
                if not isinstance(data, dict):
                    raise ValueError("A leitura deve ser um objeto JSON.")
                pendentes.append(normalize(
                    firebase_id=firebase_id, **{id_field: device_id}, data=data,
                ))
            except WorkerLockLostError:
                raise
            except Exception as error:
                erros += 1
                rejeitados.append(Rejection(
                    source, device_id, firebase_id, data,
                    f"{type(error).__name__}: {error}",
                ))
                self.logger.error(
                    f"Falha ao normalizar {source} | Equipamento: {device_id} | "
                    f"Firebase ID: {firebase_id} | Tipo: {type(error).__name__}"
                )
        falhou_banco = False
        if pendentes:
            try:
                criados = repository.insert_many(pendentes)
                inseridos += criados
                ignorados += len(pendentes) - criados
            except (DataError, IntegrityError):
                criados, existentes, falhas, rejeicoes_sql = self._persist_individually(
                    repository, pendentes, registros, source, device_id,
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
                    f"Falha ao gravar {source} | Equipamento: {device_id} | "
                    f"Tipo: {type(error).__name__}"
                )
        if rejeitados:
            try:
                self.rejections.save_many(rejeitados)
            except WorkerLockLostError:
                raise
            except Exception as error:
                falhou_banco = True
                self.logger.error(
                    f"Falha ao salvar rejeições de {source} | Equipamento: {device_id} | "
                    f"Tipo: {type(error).__name__}"
                )

        return (recebidos, inseridos, ignorados, erros), not falhou_banco

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
