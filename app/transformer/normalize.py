"""
Transforma os dados brutos do Firebase
em objetos de domínio.
"""

from app.models.sensor import Sensor
from app.models.buoy import Buoy

from app.transformer.mapper import FieldMapper
from app.transformer.timestamp import (
    sensor_timestamp,
    buoy_timestamp,
)


def _to_float(value):
    """
    Converte um valor para float.

    Valores None ou strings vazias são tratados como None.
    """

    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return None

    return float(value)


def normalize_sensor(
    firebase_id: str,
    sensor_id: str,
    data: dict,
) -> Sensor:
    """
    Converte um registro de sensor do Firebase
    em um objeto Sensor.
    """

    normalized = {}

    for key, value in data.items():

        if key in FieldMapper.SENSOR:
            normalized[FieldMapper.SENSOR[key]] = value

    normalized["firebase_id"] = firebase_id
    normalized["sensor_id"] = sensor_id

    normalized["timestamp"] = sensor_timestamp(
        normalized.pop("timestamp")
    )

    return Sensor(**normalized)


def normalize_buoy(
    firebase_id: str,
    buoy_id: str,
    data: dict,
) -> Buoy:
    """
    Converte um registro de boia do Firebase
    em um objeto Buoy.
    """

    normalized = {}

    for key, value in data.items():

        if key in FieldMapper.BUOY:
            normalized[FieldMapper.BUOY[key]] = value

    timestamp = buoy_timestamp(
        normalized.pop("data"),
        normalized.pop("hora"),
    )

    normalized["adc"] = _to_float(
        normalized.get("adc")
    )

    normalized["ph"] = _to_float(
        normalized.get("ph")
    )

    normalized["sensor_uv_v"] = _to_float(
        normalized.get("sensor_uv_v")
    )

    normalized["tensao_v"] = _to_float(
        normalized.get("tensao_v")
    )

    normalized["turbidez_v"] = _to_float(
        normalized.get("turbidez_v")
    )

    normalized["firebase_id"] = firebase_id
    normalized["buoy_id"] = buoy_id
    normalized["timestamp"] = timestamp

    return Buoy(**normalized)
