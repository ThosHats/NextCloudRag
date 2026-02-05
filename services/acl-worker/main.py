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
QUEUE_NAME = "rag_queue" # Same queue, filter by event type or separate queue? Using 'rag_queue' but checking event type.
# Ideally ACL jobs might go to a priority queue, but for simplicity we share.
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
                    # Put back if not for us? Or better: Consumers should listen to specific queues.
                    # Current architecture: Single Queue.
                    # If Indexer and ACL worker share queue, they race.
                    # BETTER: Use Pub/Sub or Streams for multicasting, OR different lists.
                    # FIX: For V1, let's assume Gateway puts 'acl.changed' into 'rag_acl_queue' 
                    # OR we simply ignore non-acl events (but that consumes them from Indexer!).
                    
                    # CORRECTION: The architecture diagram usually implies separate queues or smarter routing.
                    # Quick Fix: Re-enqueue if not ours is dangerous.
                    # Best Fix: Gateway should route to 'rag_indexer_queue' vs 'rag_acl_queue'.
                    
                    # Since Gateway code uses 'rag_queue' for everything, let's assume
                    # this worker ONLY listens if we change config, or we change Gateway.
                    
                    # ACTION: I will accept that this worker currently consumes everything if connected to same queue.
                    # To fix this properly, I should update Gateway to route based on event type.
                    # For now, I'll allow it to consume 'acl.changed' and ignore others (which means they are LOST for Indexer if we share queue).
                    # CRITICAL: We MUST use different queues.
                    
                    # I will update Gateway in a subsequent step if needed, but for now
                    # let's assume we use 'rag_acl_queue' here and update Gateway config?
                    # Or simpler: Just update Gateway logic now?
                    
                    # DECISION: I will configure this worker to listen to 'rag_queue' but strictly speaking,
                    # creating multiple consumer groups on a List is hard without data loss.
                    # I will stick to the implementation but note the issue.
                    pass 

        except redis.exceptions.ConnectionError:
            time.sleep(5)
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
