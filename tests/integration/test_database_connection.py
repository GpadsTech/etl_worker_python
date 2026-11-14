"""Conectividade real com PostgreSQL (opt-in)."""

import unittest

from app.database.connection import DatabaseConnection
from tests.integration.gate import integration_test


@integration_test
class TestDatabaseConnection(unittest.TestCase):
    def test_database_connection(self):
        db = DatabaseConnection()
        self.addCleanup(db.close)
        with db.connect().cursor() as cursor:
            cursor.execute("SELECT current_database(), version();")
            result = cursor.fetchone()
        self.assertTrue(result[0])
        print(f"\nBanco: {result[0]}\nVersão: {result[1]}")
