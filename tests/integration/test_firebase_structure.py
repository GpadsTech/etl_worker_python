"""Verifica as raízes do Firebase sem baixar o histórico completo."""

import unittest

from app.firebase.client import FirebaseClient
from tests.integration.gate import integration_test


@integration_test
class TestFirebaseStructure(unittest.TestCase):
    def test_firebase_structure(self):
        client = FirebaseClient()
        client.connect()
        for source in (client.sensors(), client.buoys()):
            devices = source.get(shallow=True)
            self.assertIsInstance(devices, dict)
            print(f"\nEquipamentos: {sorted(devices)}")
