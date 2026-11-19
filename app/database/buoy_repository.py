from app.database.base_repository import BaseRepository


class BuoyRepository(BaseRepository):

    table_name = "buoy_data"
    conflict_columns = ("buoy_id", "firebase_id")
