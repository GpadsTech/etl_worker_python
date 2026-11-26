"""Falhas controladas; commits/checkpoints reais, apenas tabelas TEMP."""

from unittest.mock import Mock, patch

from app.worker.etl_worker import ETLWorker
from tests.pagination_scenarios import PaginationScenarios
from tests.integration.temporary_database import TemporaryDatabaseTestCase
from tests.integration.gate import integration_test


@integration_test
class TestSQLPagination(PaginationScenarios, TemporaryDatabaseTestCase):
    def new_worker(self):
        with patch("app.worker.etl_worker.DatabaseConnection", return_value=self.database), \
                patch("app.worker.etl_worker.FirebaseClient"):
            worker = ETLWorker()
        worker.logger = Mock()
        return worker

    def count(self):
        with self.database.connect().cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_temp.sensor_data")
            return cursor.fetchone()[0]
