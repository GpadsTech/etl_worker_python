"""
Converte datas e horas para objetos datetime
"""

from datetime import datetime


def sensor_timestamp(value: str) -> datetime:
    """
    Converte o campo Hora do sensor para datetime.
    """

    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def buoy_timestamp(data: str, hora: str) -> datetime:
    """
    Converte Data + Hora da boia para datetime.
    """

    value = f"{data} {hora}"

    return datetime.strptime(value, "%d/%m/%Y %H:%M:%S")