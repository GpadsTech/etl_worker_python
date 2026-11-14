"""Autorização explícita, inclusive ao executar um módulo diretamente."""

import os
import unittest


integration_test = unittest.skipUnless(
    os.environ.get("RUN_INTEGRATION") == "1",
    "Integração desativada: use RUN_INTEGRATION=1 (acessa serviços reais).",
)
