"""
Transforma os dados brutos do Firebase
em objetos de domínio.
"""

import math

from app.models.sensor import Sensor
from app.models.buoy import Buoy

from app.transformer.mapper import FieldMapper
from app.transformer.timestamp import (
    sensor_timestamp,
    buoy_timestamp,
)


SENSOR_NUMERIC_FIELDS = (
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

BUOY_NUMERIC_FIELDS = (
    "adc",
    "ph",
    "sensor_uv_v",
    "tensao_v",
    "turbidez_v",
)

# Campos que fisicamente não podem assumir valores negativos.
# Trata-se de uma checagem de sanidade, não de calibração.
NON_NEGATIVE_FIELDS = frozenset({
    "ar",
    "chuva",
    "gas",
    "luz",
    "pressao",
    "rpm",
    "umidade",
    "vento",
    "volt",
})

# Limites superiores seguros. Os demais campos ficam sem teto
# até que unidades e calibração sejam confirmadas pelo firmware.
MAX_VALUE = {
    "umidade": 100.0,
}


def _to_float(value, field: str = "valor") -> float | None:
    """
    Converte um valor para float.

    Valores None, strings vazias ou apenas com espaços são tratados
    como None. Booleanos, valores não finitos (NaN/Inf) e textos que
    não representam números geram ValueError com o nome do campo.
    """

    if value is None:
        return None

    if isinstance(value, bool):
        raise ValueError(
            f"Campo '{field}' não aceita booleano: {value!r}"
        )

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return None

        try:
            number = float(value)
        except ValueError as error:
            raise ValueError(
                f"Campo '{field}' com valor numérico inválido: "
                f"{value!r}"
            ) from error

    elif isinstance(value, (int, float)):
        number = float(value)

    else:
        raise ValueError(
            f"Campo '{field}' com tipo não numérico: "
            f"{type(value).__name__}"
        )

    if not math.isfinite(number):
        raise ValueError(
            f"Campo '{field}' com valor não finito: {value!r}"
        )

    return number


def _validate_sensor_value(
    field: str,
    value: float | None,
) -> None:
    """
    Aplica checagens de sanidade a um campo numérico de sensor.

    Campos ausentes ou vazios (None) são aceitos. A validação não
    substitui a calibração: serve para impedir que valores
    claramente impossíveis cheguem ao banco.
    """

    if value is None:
        return

    if field in NON_NEGATIVE_FIELDS and value < 0:
        raise ValueError(
            f"Campo '{field}' não pode ser negativo: {value}"
        )

    maximum = MAX_VALUE.get(field)

    if maximum is not None and value > maximum:
        raise ValueError(
            f"Campo '{field}' excede o máximo de sanidade "
            f"({maximum}): {value}"
        )


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

    for field in SENSOR_NUMERIC_FIELDS:

        value = _to_float(
            normalized.get(field),
            field,
        )

        _validate_sensor_value(field, value)

        normalized[field] = value

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
        normalized.pop("timestamp"),
    )

    for field in BUOY_NUMERIC_FIELDS:

        normalized[field] = _to_float(
            normalized.get(field),
            field,
        )

    normalized["firebase_id"] = firebase_id
    normalized["buoy_id"] = buoy_id
    normalized["timestamp"] = timestamp

    return Buoy(**normalized)
