"""
Fornece um logger único para toda a aplicação.
"""

import logging
import colorlog


def get_logger() -> logging.Logger:
    """
    Cria e retorna o logger principal da aplicação.
    """

    logger = colorlog.getLogger("moringa-etl")

    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.INFO)

    handler = colorlog.StreamHandler()

    formatter = colorlog.ColoredFormatter(
        "%(log_color)s[%(levelname)s]%(reset)s %(message)s",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )

    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger