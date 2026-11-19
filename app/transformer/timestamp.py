"""
Converte datas e horas para objetos datetime.

Sensores e boias usam o mesmo formato de data/hora no Firebase
atual: ``AAAA-MM-DD HH:MM:SS``. As duas funções são mantidas
separadas para preservar a intenção de domínio de cada origem.
O responsável confirmou America/Sao_Paulo também para o histórico.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
SOURCE_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _source_timestamp(value: str) -> datetime:
    """Interpreta hora local; não escolhe silenciosamente durante transições DST."""
    local = datetime.strptime(value, TIMESTAMP_FORMAT)
    candidates = {}
    for fold in (0, 1):
        aware = local.replace(tzinfo=SOURCE_TIMEZONE, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(SOURCE_TIMEZONE).replace(tzinfo=None) == local:
            candidates.setdefault(utc, aware)
    if not candidates:
        raise ValueError("Hora inexistente em America/Sao_Paulo.")
    if len(candidates) > 1:
        raise ValueError("Hora ambígua em America/Sao_Paulo; offset da origem necessário.")
    return next(iter(candidates.values()))


def sensor_timestamp(value: str) -> datetime:
    """
    Converte o campo ``hora`` do sensor para datetime.
    """

    return _source_timestamp(value)


def buoy_timestamp(value: str) -> datetime:
    """
    Converte o campo ``hora`` da boia para datetime.

    A boia não envia mais os campos separados ``Data`` e ``Hora``;
    o registro traz um único ``hora`` já completo.
    """

    return _source_timestamp(value)
