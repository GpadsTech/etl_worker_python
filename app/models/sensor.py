"""
Modelo de domínio para sensores. Representa uma linha da tabela 'sensores'
do PostgreSQL
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Sensor:

    firebase_id: str
    sensor_id: str

    timestamp: datetime

    ar: float | None = None
    chuva: float | None = None
    gas: float | None = None
    luz: float | None = None
    pressao: float | None = None
    rpm: float | None = None
    temperatura: float | None = None
    umidade: float | None = None
    vento: float | None = None
    volt: float | None = None
