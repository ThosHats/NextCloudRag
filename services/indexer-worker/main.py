import os
import json
import time
import logging
import tempfile
import redis
from src.webdav_client import NextcloudClient
from src.pipeline import IndexingPipeline
from src.db import MetadataDB

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indexer-worker")

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "rag_queue"
NEXTCLOUD_URL = os.getenv("NEXTCLOUD_URL")
WEBDAV_USER = os.getenv("WEBDAV_USER")
WEBDAV_PASSWORD = os.getenv("WEBDAV_PASSWORD")

def process_job(job: dict, pipeline: IndexingPipeline, nc_client: NextcloudClient, db: MetadataDB):
    payload = job.get("payload", {})
    event = payload.get("event")
    file_id = payload.get("file_id")
    file_path = payload.get("path", "") # Need to ensure we get the full path
    
    logger.info(f"Processing event {event} for file {file_path} (ID: {file_id})")

    if event in ["file.created", "file.updated"]:
        # 1. Download file
        # Note: Nextcloud paths in webhooks might need adjustment (e.g. removing user prefix)
        # For now, we assume path is usable.
        try:
            content_io = nc_client.download_file(file_path)
            
            # 2. Save to temp file for Haystack (most converters need a path)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(content_io.read())
                tmp_path = tmp.name
            
            # 3. Index
            meta = {
                "file_id": str(file_id),
                "path": file_path,
                "etag": payload.get("etag")
            }
            pipeline.run(tmp_path, meta)
            
            # 4. Update DB
            db.upsert_file(str(file_id), file_path, payload.get("etag"))
            
            # Cleanup
            os.remove(tmp_path)
            logger.info(f"Successfully indexed {file_path}")
            
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            raise

    elif event == "file.deleted":
        # TODO: Implement deletion logic in Pipeline/DB
        logger.info(f"File deletion not yet fully implemented for {file_id}")
        pass

def main():
    logger.info("Starting Indexer Worker...")
    
    # Initialize connections
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        nc_client = NextcloudClient(NEXTCLOUD_URL + "/remote.php/dav/files/" + WEBDAV_USER, (WEBDAV_USER, WEBDAV_PASSWORD))
        pipeline = IndexingPipeline()
        db = MetadataDB()
        logger.info("Connections initialized.")
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        return

    # Consumer Loop
    while True:
        try:
            # Blocking pop
            item = redis_client.brpop(QUEUE_NAME, timeout=5)
            if item:
                _, job_json = item
                job = json.loads(job_json)
                process_job(job, pipeline, nc_client, db)
        except redis.exceptions.ConnectionError:
            logger.error("Redis connection lost, retrying...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error in loop: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
