import os
import time
import json
import logging
import redis
import schedule
import threading
from src.acl_client import NextcloudACLClient
from src.qdrant_updater import QdrantUpdater

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("acl-worker")

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.getenv("ACL_QUEUE_NAME", "rag_acl_queue")
NEXTCLOUD_URL = os.getenv("NEXTCLOUD_URL")
WEBDAV_USER = os.getenv("WEBDAV_USER")
WEBDAV_PASSWORD = os.getenv("WEBDAV_PASSWORD")

def reconcile_all():
    logger.info("Starting scheduled ACL reconciliation...")
    # TODO: Iterate over all known files in DB/Qdrant and refresh ACLs
    # This requires listing from Postgres
    pass

def process_acl_job(job: dict, acl_client: NextcloudACLClient, updater: QdrantUpdater):
    payload = job.get("payload", {})
    event = payload.get("event")
    file_id = payload.get("file_id")
    file_path = payload.get("path")

    if event == "acl.changed" or event == "file.created":
        logger.info(f"Processing ACL update for {file_id}")
        try:
            acl_data = acl_client.fetch_acl(file_path)
            updater.update_acl(file_id, acl_data)
        except Exception as e:
            logger.error(f"Error updating ACL: {e}")

def run_scheduler():
    schedule.every(10).minutes.do(reconcile_all)
    while True:
        schedule.run_pending()
        time.sleep(1)

def main():
    logger.info("Starting ACL Worker...")
    
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        acl_client = NextcloudACLClient(NEXTCLOUD_URL, (WEBDAV_USER, WEBDAV_PASSWORD))
        updater = QdrantUpdater()
        
        # Start Scheduler in background thread
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        
        logger.info("Connections initialized. Waiting for jobs...")
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        return

    while True:
        try:
            item = redis_client.brpop(QUEUE_NAME, timeout=5)
            if item:
                _, job_json = item
                job = json.loads(job_json)
                payload = job.get("payload", {})
                
                # Filter for ACL related events
                # Note: 'file.created' also needs initial ACL set if Indexer didn't do it fully?
                # Actually Indexer creates the point, ACL worker might refine it.
                # OR we just listen for explicit 'acl.changed' events here.
                if payload.get("event") == "acl.changed":
                    process_acl_job(job, acl_client, updater)
                else:
                    # Non-ACL events are expected on different queues and are ignored here.
                    pass

        except redis.exceptions.ConnectionError:
            time.sleep(5)
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
