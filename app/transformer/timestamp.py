"""
Converte datas e horas para objetos datetime.

Sensores e boias usam o mesmo formato de data/hora no Firebase
atual: ``AAAA-MM-DD HH:MM:SS``. As duas funções são mantidas
separadas para preservar a intenção de domínio de cada origem.
"""

from datetime import datetime


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def sensor_timestamp(value: str) -> datetime:
    """
    Converte o campo ``hora`` do sensor para datetime.
    """

    return datetime.strptime(value, TIMESTAMP_FORMAT)


def buoy_timestamp(value: str) -> datetime:
    """
    Converte o campo ``hora`` da boia para datetime.

    A boia não envia mais os campos separados ``Data`` e ``Hora``;
    o registro traz um único ``hora`` já completo.
    """

    return datetime.strptime(value, TIMESTAMP_FORMAT)
