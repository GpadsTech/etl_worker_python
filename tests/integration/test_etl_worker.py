"""
Teste de integração do ETLWorker.
"""

import unittest
from unittest.mock import patch

from app.worker.etl_worker import ETLWorker
from tests.integration.temporary_database import TemporaryDatabaseTestCase


from tests.integration.gate import integration_test


@integration_test
class TestETLWorker(TemporaryDatabaseTestCase):

    def test_run_once(self):

        # Todos os repositórios, inclusive checkpoints, usam a mesma sessão TEMP.
        with patch("app.worker.etl_worker.DatabaseConnection", return_value=self.database):
            worker = ETLWorker()

        sensores, boias = worker.run_once()

        (
            sensores_recebidos,
            sensores_inseridos,
            sensores_ignorados,
            sensores_erros,
        ) = sensores

        (
            boias_recebidas,
            boias_inseridas,
            boias_ignoradas,
            boias_erros,
        ) = boias

        print("\nResultado:")

        print(
            f"Sensores -> "
            f"recebidos: {sensores_recebidos}, "
            f"inseridos: {sensores_inseridos}, "
            f"já existentes: {sensores_ignorados}, "
            f"erros: {sensores_erros}"
        )

        print(
            f"Boias -> "
            f"recebidos: {boias_recebidas}, "
            f"inseridos: {boias_inseridas}, "
            f"já existentes: {boias_ignoradas}, "
            f"erros: {boias_erros}"
        )

        # Zero recebidos é válido quando o checkpoint está atualizado.
        self.assertGreaterEqual(sensores_recebidos, 0)
        self.assertGreaterEqual(boias_recebidas, 0)
        self.assertEqual(sensores_erros, 0)
        self.assertEqual(boias_erros, 0)

        # Todo registro recebido deve terminar em:
        # inserido, ignorado ou erro
        self.assertEqual(
            sensores_recebidos,
            sensores_inseridos
            + sensores_ignorados
            + sensores_erros
        )

        self.assertEqual(
            boias_recebidas,
            boias_inseridas
            + boias_ignoradas
            + boias_erros
        )
