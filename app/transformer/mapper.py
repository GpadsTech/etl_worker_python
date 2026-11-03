"""
faz o mapeamento entre os campos do Firebase
e os nomes padronizados utilizados no ETL
"""


class FieldMapper:
    """
    Centraliza todos os mapeamentos de campos utilizados pelo ETL.
    """

    SENSOR = {
        "Ar": "ar",
        "Chuva": "chuva",
        "Gas": "gas",
        "Hora": "timestamp",
        "Luz": "luz",
        "Pressao": "pressao",
        "Rpm": "rpm",
        "Temperatura": "temperatura",
        "Umidade": "umidade",
        "Vento": "vento",
        "Volt": "volt",
    }

    BUOY = {
        "ADC": "adc",
        "Data": "data",
        "Hora": "hora",
        "Ph": "ph",
        "Sensor UV(V)": "sensor_uv_v",
        "Tensão(V)": "tensao_v",
        "Turbidez(V)": "turbidez_v",
    }