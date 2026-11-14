"""
Repository responsável pela persistência de sensores
no PostgreSQL / TimescaleDB.

A política de conflito (histórico append-only) está documentada em
``app/repository/base.py``.
"""

from app.repository.base import BaseRepository


class SensorRepository(BaseRepository):
    """
    Insere leituras de sensores na tabela ``sensor_data``.
    """

    table_name = "sensor_data"

    columns = (
        "firebase_id",
        "sensor_id",
        "timestamp",
        "ar",
        "chuva",
        "gas",
        "luz",
        "pressao",
        "rpm",
        "temperatura",
        "umidade",
        "vento",
        "volt",
    )
