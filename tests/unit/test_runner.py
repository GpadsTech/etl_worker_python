"""O runner padrão é offline; integração sem opt-in não chama serviços."""

import unittest

from tests.runner import build_suite


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


class TestRunner(unittest.TestCase):
    def test_default_only_discovers_unit_tests(self):
        ids = [test.id() for test in cases(build_suite([]))]
        self.assertTrue(ids)
        self.assertTrue(all(name.startswith("tests.unit.") for name in ids))
        self.assertTrue(any("test_batch_repository" in name for name in ids))

    def test_all_excludes_legacy_bootstrap(self):
        ids = [test.id() for test in cases(build_suite(["all"]))]
        self.assertFalse(any(
            name.startswith("tests.legacy.") or ".test_bootstrap." in name
            for name in ids
        ))
        self.assertTrue(any("tests.integration." in name for name in ids))

    def test_integration_is_skipped_without_touching_services(self):
        # Importação nova para avaliar o gate com ambiente explicitamente limpo.
        import subprocess
        import os
        import sys

        environment = dict(os.environ)
        environment.pop("RUN_INTEGRATION", None)
        script = """
import io
import unittest
from unittest.mock import patch
from tests.runner import build_suite
with (
    patch('app.firebase.client.FirebaseClient.connect',
          side_effect=AssertionError('Firebase real proibido')),
    patch('app.database.connection.DatabaseConnection.connect',
          side_effect=AssertionError('PostgreSQL real proibido')),
):
    result = unittest.TextTestRunner(stream=io.StringIO()).run(
        build_suite(['integration']))
assert result.wasSuccessful(), (result.errors, result.failures)
assert result.testsRun > 0
assert len(result.skipped) == result.testsRun
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            env=environment, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_direct_integration_module_is_also_gated(self):
        # O teste acima já importa módulos com seus próprios decorators.
        suite = build_suite(["tests.integration.test_etl_worker"])
        self.assertEqual(suite.countTestCases(), 1)
