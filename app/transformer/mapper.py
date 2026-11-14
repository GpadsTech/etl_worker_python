"""
faz o mapeamento entre os campos do Firebase
e os nomes padronizados utilizados no ETL

O schema atual do Firebase usa chaves em minúsculas
(ex.: ``hora``, ``temperatura``, ``sensor_uv_v``).

Os nomes em maiúsculas (``Hora``, ``Temperatura``, ``Sensor UV(V)``)
pertencem a um formato antigo que não é mais produzido. Eles foram
removidos de propósito: manter as duas variantes criaria ambiguidade
caso um mesmo registro trouxesse as duas chaves.

Campos de metadados (``endereco_ip`` e ``identificador``) não são
mapeados e, portanto, são descartados de forma intencional.
"""


class FieldMapper:
    """
    Centraliza todos os mapeamentos de campos utilizados pelo ETL.
    """

    SENSOR = {
        "ar": "ar",
        "chuva": "chuva",
        "gas": "gas",
        "hora": "timestamp",
        "luz": "luz",
        "pressao": "pressao",
        "rpm": "rpm",
        "temperatura": "temperatura",
        "umidade": "umidade",
        "vento": "vento",
        "volt": "volt",
    }

    BUOY = {
        "adc": "adc",
        "hora": "timestamp",
        "ph": "ph",
        "sensor_uv_v": "sensor_uv_v",
        "tensao_v": "tensao_v",
        "turbidez_v": "turbidez_v",
    }
