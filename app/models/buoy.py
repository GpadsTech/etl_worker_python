"""
Modelo de domínio para boias. Representa uma linha da tabela 'boias'
do PostgreSQL
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Buoy:

    firebase_id: str
    buoy_id: str

    timestamp: datetime

    adc: float | None = None
    ph: float | None = None
    sensor_uv_v: float | None = None
    tensao_v: float | None = None
    turbidez_v: float | None = None
