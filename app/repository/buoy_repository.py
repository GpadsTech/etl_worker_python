"""
Repository responsável pela persistência de boias
no PostgreSQL.

A política de conflito (histórico append-only) está documentada em
``app/repository/base.py``.
"""

from app.repository.base import BaseRepository


class BuoyRepository(BaseRepository):
    """
    Insere leituras de boias na tabela ``buoy_data``.
    """

    table_name = "buoy_data"
    conflict_columns = ("buoy_id", "firebase_id")

    columns = (
        "firebase_id",
        "buoy_id",
        "timestamp",
        "adc",
        "ph",
        "sensor_uv_v",
        "tensao_v",
        "turbidez_v",
    )
