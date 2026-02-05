import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class MetadataDB:
    def __init__(self):
        self.dsn = os.getenv("POSTGRES_URL")

    def get_connection(self):
        return psycopg2.connect(self.dsn)

    def upsert_file(self, file_id: str, path: str, etag: str):
        """
        Updates the file metadata table.
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS files (
                        file_id VARCHAR PRIMARY KEY,
                        path TEXT NOT NULL,
                        etag VARCHAR,
                        last_indexed TIMESTAMP
                    );
                """)
                cur.execute("""
                    INSERT INTO files (file_id, path, etag, last_indexed)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (file_id) DO UPDATE 
                    SET path = EXCLUDED.path, etag = EXCLUDED.etag, last_indexed = EXCLUDED.last_indexed;
                """, (file_id, path, etag, datetime.utcnow()))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"DB Error: {e}")
            raise
        finally:
            conn.close()

    def mark_deleted(self, file_id: str):
        # Implementation for deletion/status update
        pass
