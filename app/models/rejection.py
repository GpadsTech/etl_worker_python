"""Leitura rejeitada, preservada para diagnóstico e reprocessamento."""

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Rejection:
    source: str
    device_id: str
    firebase_id: str
    payload: Any
    reason: str
