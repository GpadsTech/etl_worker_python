"""
Ponto de entrada da aplicação GPADS ETL.
"""

import time

from app.utils.logger import get_logger
from app.config.config import config
from app.worker.etl_worker import ETLWorker


def main() -> None:
    """
    Inicializa e executa o worker ETL continuamente.
    """

    logger = get_logger()

    logger.info("=" * 70)
    logger.info("GPADS ETL")
    logger.info("=" * 70)

    logger.info("Carregando configurações...")
    logger.info(
        f"Firebase: {config.FIREBASE_DATABASE_URL}"
    )

    logger.info(
        f"Intervalo do ETL: "
        f"{config.ETL_INTERVAL_SECONDS} segundos"
    )

    worker = ETLWorker()

    logger.info("ETL Worker iniciado.")

    try:

        while True:

            try:

                logger.info("Iniciando novo ciclo do ETL...")

                sensores, boias = worker.run_once()

                logger.info(
                    f"Ciclo concluído | "
                    f"Sensores recebidos: {sensores[0]} | "
                    f"Sensores inseridos: {sensores[1]} | "
                    f"Sensores existentes: {sensores[2]} | "
                    f"Sensores com erro: {sensores[3]}"
                )

                logger.info(
                    f"Ciclo concluído | "
                    f"Boias recebidas: {boias[0]} | "
                    f"Boias inseridas: {boias[1]} | "
                    f"Boias existentes: {boias[2]} | "
                    f"Boias com erro: {boias[3]}"
                )

            except Exception:

                logger.exception(
                    "Erro durante o ciclo do ETL."
                )

            logger.info(
                f"Aguardando "
                f"{config.ETL_INTERVAL_SECONDS} segundos "
                f"para o próximo ciclo..."
            )

            time.sleep(
                config.ETL_INTERVAL_SECONDS
            )

    except KeyboardInterrupt:

        logger.info(
            "Worker interrompido pelo usuário."
        )

    finally:

        worker.database.close()

        logger.info(
            "Conexão com o banco encerrada."
        )

        logger.info(
            "GPADS ETL finalizado."
        )


if __name__ == "__main__":
    main()