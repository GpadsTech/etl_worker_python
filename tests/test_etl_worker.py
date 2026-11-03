"""
Teste de integração do ETLWorker.
"""

import unittest

from app.worker.etl_worker import ETLWorker


class TestETLWorker(unittest.TestCase):

    def test_run_once(self):

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

        # Deve ter registros vindos do Firebase
        self.assertGreater(sensores_recebidos, 0)
        self.assertGreater(boias_recebidas, 0)

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