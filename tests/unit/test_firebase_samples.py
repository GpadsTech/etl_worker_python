"""Descoberta dinâmica validada com Firebase simulado, sem rede."""

import unittest
from unittest.mock import Mock, call

from app.transformer.normalize import normalize_sensor
from tests.integration.firebase_samples import buscar_leitura_real


class TestFirebaseSamples(unittest.TestCase):
    def setUp(self):
        self.client = Mock()

    def query(self, source="sensores"):
        reference = (
            self.client.sensor_data if source == "sensores"
            else self.client.buoy_data
        )
        return reference.return_value.order_by_key.return_value.limit_to_last.return_value

    def test_selects_sensor_dynamically_with_bounded_query(self):
        self.client.sensors.return_value.get.return_value = {
            "EST_NOVO_Z": True, "EST_NOVO_A": True,
        }
        data = {"hora": "2026-08-20 17:29:06", "temperatura": 25}
        self.query().get.return_value = {"-ultima": data}

        self.assertEqual(
            buscar_leitura_real(self.client, "sensores"),
            ("EST_NOVO_A", "-ultima", data),
        )
        self.client.connect.assert_called_once_with()
        self.client.sensors.return_value.get.assert_called_once_with(shallow=True)
        self.client.sensor_data.assert_called_once_with("EST_NOVO_A")
        reference = self.client.sensor_data.return_value
        reference.order_by_key.assert_called_once_with()
        reference.order_by_key.return_value.limit_to_last.assert_called_once_with(1)
        reference.get.assert_not_called()
        self.client.buoys.assert_not_called()

    def test_selects_buoy_dynamically(self):
        self.client.buoys.return_value.get.return_value = {"BOIA_NOVA": True}
        self.query("boias").get.return_value = {"-ultima": {"ph": 7}}
        self.assertEqual(
            buscar_leitura_real(self.client, "boias"),
            ("BOIA_NOVA", "-ultima", {"ph": 7}),
        )
        self.client.buoy_data.assert_called_once_with("BOIA_NOVA")
        self.client.sensors.assert_not_called()

    def test_empty_equipment_is_skipped_before_next_device(self):
        self.client.sensors.return_value.get.return_value = {"B": True, "A": True}
        self.query().get.side_effect = [None, {"-key": {"hora": "inválida"}}]
        self.assertEqual(
            buscar_leitura_real(self.client, "sensores"),
            ("B", "-key", {"hora": "inválida"}),
        )
        self.assertEqual(self.client.sensor_data.call_args_list, [call("A"), call("B")])

    def test_no_devices_skips_with_reason(self):
        for devices in (None, {}):
            with self.subTest(devices=devices):
                self.client.sensors.return_value.get.return_value = devices
                with self.assertRaisesRegex(unittest.SkipTest, "Sem equipamentos"):
                    buscar_leitura_real(self.client, "sensores")
        self.client.sensor_data.assert_not_called()

    def test_no_readings_skips_with_reason(self):
        self.client.sensors.return_value.get.return_value = {"A": True, "B": True}
        self.query().get.side_effect = [None, {}]
        with self.assertRaisesRegex(unittest.SkipTest, "Sem leituras"):
            buscar_leitura_real(self.client, "sensores")
        self.assertEqual(self.client.sensor_data.call_count, 2)

    def test_connection_error_is_not_hidden_as_skip(self):
        self.client.connect.side_effect = ConnectionError("sem conexão")
        with self.assertRaisesRegex(ConnectionError, "sem conexão"):
            buscar_leitura_real(self.client, "sensores")

    def test_permission_error_is_not_hidden_as_skip(self):
        self.client.sensors.return_value.get.return_value = {"A": True}
        self.query().get.side_effect = PermissionError("acesso negado")
        with self.assertRaisesRegex(PermissionError, "acesso negado"):
            buscar_leitura_real(self.client, "sensores")

    def test_invalid_root_is_a_failure_not_skip(self):
        self.client.sensors.return_value.get.return_value = ["A"]
        with self.assertRaisesRegex(AssertionError, "Formato inválido"):
            buscar_leitura_real(self.client, "sensores")

    def test_invalid_records_are_a_failure_not_skip(self):
        self.client.sensors.return_value.get.return_value = {"A": True}
        for records in ([], "inválido", {"-key": 42}, {"-a": {}, "-b": {}}):
            with self.subTest(records=records):
                self.query().get.return_value = records
                with self.assertRaises(AssertionError):
                    buscar_leitura_real(self.client, "sensores")

    def test_invalid_measurement_reaches_normalization_and_fails(self):
        self.client.sensors.return_value.get.return_value = {"A": True}
        self.query().get.return_value = {
            "-key": {"hora": "2026-08-20 17:29:06", "temperatura": "inválida"},
        }
        device_id, firebase_id, data = buscar_leitura_real(self.client, "sensores")
        with self.assertRaises(ValueError):
            normalize_sensor(firebase_id, device_id, data)

    def test_unknown_source_does_not_connect(self):
        with self.assertRaisesRegex(ValueError, "Origem não suportada"):
            buscar_leitura_real(self.client, "desconhecida")
        self.client.connect.assert_not_called()
