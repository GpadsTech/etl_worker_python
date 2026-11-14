"""Seleção de uma leitura real, sem depender de identificadores fixos."""

from unittest import SkipTest


def buscar_leitura_real(client, source: str) -> tuple[str, str, dict]:
    """Retorna equipamento, chave e conteúdo; ausência de dados pula o teste.

    Erros de conexão, permissão ou formato são propagados, não tratados como
    ausência de dados. A validação dos campos cabe ao teste consumidor.
    """
    if source == "sensores":
        root = client.sensors
        data_reference = client.sensor_data
    elif source == "boias":
        root = client.buoys
        data_reference = client.buoy_data
    else:
        raise ValueError(f"Origem não suportada: {source!r}")

    client.connect()
    devices = root().get(shallow=True)

    if devices is None or devices == {}:
        raise SkipTest(f"Sem equipamentos em /{source} para testar uma leitura real.")
    if not isinstance(devices, dict):
        raise AssertionError(f"Formato inválido em /{source}: esperado um dicionário.")

    for device_id in sorted(devices):
        records = (
            data_reference(device_id)
            .order_by_key()
            .limit_to_last(1)
            .get()
        )
        if records is None or records == {}:
            continue
        if not isinstance(records, dict) or len(records) != 1:
            raise AssertionError(
                f"Formato inválido em /{source}/{device_id}/dados: "
                "esperada uma única leitura."
            )

        firebase_id, data = next(iter(records.items()))
        if not isinstance(data, dict):
            raise AssertionError(
                f"Leitura inválida em /{source}/{device_id}/dados/{firebase_id}: "
                "esperado um dicionário."
            )
        return device_id, firebase_id, data

    raise SkipTest(f"Sem leituras nos equipamentos de /{source}.")
