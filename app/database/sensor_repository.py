from app.database.base_repository import BaseRepository


class SensorRepository(BaseRepository):

    table_name = "sensor_data"
    conflict_columns = ("sensor_id", "firebase_id")
