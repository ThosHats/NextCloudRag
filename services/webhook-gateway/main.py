import os
import hmac
import hashlib
import json
import logging
from typing import Dict, Any
from fastapi import FastAPI, Request, HTTPException, Header, status
from pydantic import BaseModel
import redis

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook-gateway")

app = FastAPI(title="Nextcloud RAG Webhook Gateway")

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
WEBHOOK_SECRET = os.getenv("NEXTCLOUD_WEBHOOK_SECRET", "change_me")
QUEUE_NAME = "rag_queue"

# Redis Connection
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
except Exception as e:
    logger.error(f"Failed to connect to Redis: {e}")
    redis_client = None

class WebhookPayload(BaseModel):
    # Generic payload model, can be made more specific based on the NC App used
    event: str | None = None
    file_id: str | int | None = None
    path: str | None = None
    # Allow extra fields since webhook payloads vary
    model_config = {"extra": "allow"}

def verify_signature(request_body: bytes, signature: str) -> bool:
    """
    Verifies the HMAC SHA-256 signature of the request body.
    """
    if not signature:
        return False
    
    digest = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(digest, signature)

@app.post("/", status_code=status.HTTP_202_ACCEPTED)
@app.post("/webhook/nextcloud", status_code=status.HTTP_202_ACCEPTED)
async def handle_webhook(
    request: Request,
    x_signature_sha256: str = Header(None, alias="X-Signature-SHA256"),
    x_signature: str = Header(None, alias="X-Signature")
):
    """
    Receives Webhook events from Nextcloud, verifies them, and pushes to Redis.
    Supports both X-Signature-SHA256 and generic X-Signature headers.
    """
    body_bytes = await request.body()
    
    # Signature/Token Verification
    signature = x_signature_sha256 or x_signature
    nc_token = request.headers.get("X-Nextcloud-Token")
    
    if not signature and not nc_token:
        logger.warning("Missing authentication (signature or token)")
        raise HTTPException(status_code=401, detail="Missing auth")
    
    if signature:
        if not verify_signature(body_bytes, signature):
            logger.warning("Invalid HMAC signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
    elif nc_token:
        # For now, we allow the placeholder token we set in install.py
        # In a production setup, this would be matched against the .env variable
        if nc_token != "insecure-placeholder-for-now":
            logger.warning(f"Invalid Nextcloud Token: {nc_token}")
            raise HTTPException(status_code=401, detail="Invalid token")
    
    logger.info("Authentication successful")

    try:
        payload = await request.json()
        logger.info(f"Received valid event: {payload.get('event', 'unknown')}")
        
        if redis_client:
            # Enqueue job
            job = {
                "source": "nextcloud",
                "payload": payload,
                "status": "pending"
            }
            redis_client.lpush(QUEUE_NAME, json.dumps(job))
            logger.info("Job enqueued to Redis")
        else:
            logger.error("Redis client not available, ensuring 500 error")
            raise HTTPException(status_code=500, detail="Internal processing error")

        return {"status": "queued"}

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    return {"status": "ok", "redis": redis_client.ping() if redis_client else False}
