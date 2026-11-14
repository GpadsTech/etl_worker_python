"""Conectividade real com Firebase (opt-in)."""

import unittest

from app.firebase.client import FirebaseClient
from tests.integration.gate import integration_test


@integration_test
class TestFirebaseConnection(unittest.TestCase):
    def test_firebase_connection(self):
        client = FirebaseClient()
        self.assertIsNotNone(client.connect())
        data = client.sensors().get(shallow=True)
        self.assertIsInstance(data, dict)
        print(f"\nFirebase conectado: {len(data)} equipamento(s) em sensores.")
