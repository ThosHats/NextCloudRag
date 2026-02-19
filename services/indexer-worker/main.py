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
    
    # Handle both old "Webhooks" app and new official "Webhook Listeners" app
    if "event" in payload and isinstance(payload["event"], dict):
        # Official Webhook Listeners Format
        event_obj = payload["event"]
        event_class = event_obj.get("class", "")
        
        # Map class names to simplified events
        if "NodeCreatedEvent" in event_class:
            event = "file.created"
        elif "NodeWrittenEvent" in event_class:
            event = "file.updated"
        elif "NodeDeletedEvent" in event_class:
            event = "file.deleted"
        else:
            event = "unknown"
            
        node = event_obj.get("node", {})
        file_id = node.get("id")
        # Webhook Listeners paths are often 'files/username/path/to/file'
        # We need the path relative to the user's root for WebDAV
        raw_path = node.get("path", "")
        # Paths are typically: /files/{owner}/{path/to/file}
        # e.g., /files/ThomasHartkens/My Documents/Note.md
        # OR for shared files accessed by another user, the path in the event is absolute to the owner.
        
        # CRITICAL FIX: The event payload gives the path relative to the OWNER's file system,
        # but 'rag-bot' sees it in its own WebDAV structure (often under 'Shared/' or just the root if accepted).
        
        # Since we don't know exactly where 'rag-bot' mounted the share, we need robust handling.
        # IF the file is in a shared folder, the path coming from the event (owner's view) 
        # might NOT match the path in rag-bot's WebDAV (receiver's view).
        
        parts = raw_path.strip("/").split("/")
        
        # Heuristic: Try to strip the first two segments (files/{owner}) to get the relative path
        if len(parts) > 2 and parts[0] == "files":
            # path_parts[2:] is the path inside the user's home
            # e.g. "files/ThomasHartkens/Shared/Dokument.pdf" -> "Shared/Dokument.pdf"
            relative_path = "/".join(parts[2:])
        else:
            relative_path = raw_path
            
        file_path = relative_path
        etag = node.get("etag") # Might not be present in all events
    else:
        # Legacy/Simple Webhooks App Format
        event = payload.get("event")
        file_id = payload.get("file_id")
        file_path = payload.get("path", "")
        etag = payload.get("etag")
    
    logger.info(f"Processing event {event} for file {file_path} (ID: {file_id})")

    if event in ["file.created", "file.updated"]:
        # 1. Download file
        try:
            content_io = nc_client.download_file(file_path)
            
            # 2. Save to temp file for Haystack
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(content_io.read())
                tmp_path = tmp.name
            
            # 3. Index
            meta = {
                "file_id": str(file_id),
                "path": file_path,
                "etag": etag
            }
            pipeline.run(tmp_path, meta)
            
            # 4. Update DB
            db.upsert_file(str(file_id), file_path, etag)
            
            # Cleanup
            os.remove(tmp_path)
            logger.info(f"Successfully indexed {file_path}")
            
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            raise

    elif event == "file.deleted":
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
