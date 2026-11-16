"""Reprocessamento manual e limitado de rejeições; não altera checkpoints."""

import argparse

from app.utils.logger import get_logger
from app.worker.etl_worker import ETLWorker
from app.database.connection import WorkerAlreadyRunningError


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("O limite deve ser positivo.")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=positive_int, default=100)
    parser.add_argument("--source", choices=("sensores", "boias"))
    parser.add_argument("--device-id")
    parser.add_argument(
        "--refresh-from-firebase",
        action="store_true",
        help="Relê a leitura na origem em vez de usar o payload salvo.",
    )
    args = parser.parse_args(argv)
    logger = get_logger()
    worker = ETLWorker()
    try:
        attempted, inserted, existing, errors = worker.reprocess_rejections(
            limit=args.limit,
            source=args.source,
            device_id=args.device_id,
            refresh_from_firebase=args.refresh_from_firebase,
        )
        logger.info(
            f"Reprocessamento | Tentados: {attempted} | "
            f"Inseridos: {inserted} | Existentes: {existing} | Erros: {errors}"
        )
        return 1 if errors else 0
    except WorkerAlreadyRunningError:
        logger.error("Outro processo possui a trava do ETL; reprocessamento não iniciado.")
        return 1
    except Exception as error:
        logger.error(
            f"Reprocessamento interrompido | Tipo: {type(error).__name__}"
        )
        return 1
    finally:
        worker.database.close()


if __name__ == "__main__":
    raise SystemExit(main())
