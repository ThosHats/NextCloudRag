# Installation Instructions
##

This guide walks you through the deployment of the Nextcloud RAG architecture (Option 2A). Follow these steps sequentially.

## Prerequisites
- Docker Engine & Docker Compose installed.
- Root privileges (or user in `docker` group).
- Valid DNS records pointing to your server for:
    - `NEXTCLOUD_DOMAIN` (e.g., `cloud.example.com`)
    - `RAG_DOMAIN` (e.g., `rag.example.com`)

---

## Step 1: Network Setup
The system relies on a shared external network to allow communication between independent stacks.

**Action:**
```bash
docker network create platform-net
```

**Verification:**
Run the following check. It should output `platform-net`.
```bash
docker network ls | grep platform-net
```

---

## Step 2: Reverse Proxy (Caddy) Setup
We start the proxy first. We use `caddy-docker-proxy` to automatically configure SSL and routing based on Docker labels.

**Action:**
1. Navigate to the proxy directory:
   ```bash
   cd docker-deploy/proxy
   ```
2. Create and edit the configuration:
   ```bash
   cp .env.example .env
   nano .env
   # Set ACME_EMAIL
   ```
3. Start the stack:
   ```bash
   docker compose up -d
   ```

**Verification:**
Check if Caddy is running and ports are open.
```bash
docker compose ps
# Output should show 'Up' and ports 0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
```
Check logs to see ACME initialization:
```bash
docker logs caddy
```

---

## Step 3: Nextcloud AIO Setup
Nextcloud AIO manages its own containers but is routed through Caddy.

**Action:**
1. Navigate to the AIO directory:
   ```bash
   cd ../nextcloud-aio
   ```
2. Start the master container:
   ```bash
   docker compose up -d
   ```

**Verification:**
1. Wait for a moment, then check logs:
   ```bash
   docker logs nextcloud-aio-mastercontainer
   ```
   Look for: *'The AIO interface is now ready on port 8080'*
2. Open your browser at `https://your-nextcloud-domain:8443` (or the configured AIO interface port, usually it guides you).
3. **Finish the Setup Wizard:**
   - Enter your domain (`cloud.example.com`).
   - Allow it to start the child containers.
   - **Important:** Create the `readonly-bot` user and generate an App Password for the RAG system.

---

## Step 4: RAG Services (Build & Deploy)
This stack contains the custom services (Gateway, Worker, API) and the vector database.

**Action:**
1. Navigate to the RAG stack directory:
   ```bash
   cd ../rag-stack
   ```
2. Create and edit the configuration:
   ```bash
   cp .env.example .env
   nano .env
   # Fill in:
   # - WEBDAV_USER / PASSWORD (from Step 3)
   # - NEXTCLOUD_URL
   # - OIDC Settings (if available)
   # - OPENAI_API_KEY
   ```
3. Build the custom images:
   ```bash
   docker compose build
   ```
4. Start the stack:
   ```bash
   docker compose up -d
   ```

**Verification:**
1. Check that all containers are running:
   ```bash
   docker compose ps
   # Expect: rag-qdrant, rag-redis, rag-postgres, rag-webhook-gateway, rag-indexer-worker, rag-haystack-api
   ```
2. Check the logs of the API service to ensure it initialized the pipeline:
   ```bash
   docker logs rag-haystack-api | grep "RAG Pipeline initialized"
   ```

---

## Step 5: End-to-End System Test

### 5.1 Test Webhook Gateway
Simulate a Nextcloud event.

**Action:**
Use `curl` to send a mock event (adjust URL and Secret):
```bash
# Calculate HMAC signature manually if needed, or check logs for "invalid signature" to confirm connectivity.
curl -X POST https://rag.example.com/webhook/nextcloud \
     -H "Content-Type: application/json" \
     -H "X-Signature-SHA256: <valid_hmac>" \
     -d '{"event": "file.created", "file_id": "test1", "path": "/test.pdf"}'
```
*Note: Without a valid signature, you should get a 401. This confirms the service is reachable.*

### 5.2 Test Indexing Worker
Check if the worker processes jobs.

**Action:**
Observe worker logs while triggering an event (or after the curl above):
```bash
docker logs -f rag-indexer-worker
```
*Success:* You should see `Processing event...` or connection errors if WebDAV is misconfigured.

### 5.3 Test Chat API
Query the system.

**Action:**
```bash
curl -X POST https://rag.example.com/chat \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <mock_token>" \
     -d '{"query": "Hello world"}'
```
*Success:* Response should be JSON `{"answer": "...", "sources": []}`.

---

## Troubleshooting

- **Proxy Errors (502/404):** Check `docker logs caddy`. Ensure labels in `docker-compose.yml` match the intended domains.
- **Certificate Issues:** Caddy handles Let's Encrypt automatically. Check logs if SSL fails (ensure port 80/443 are open to the world).
- **Database Connection:** Ensure `rag-postgres` and `rag-qdrant` are healthy. Use `docker exec -it rag-indexer-worker ping rag-postgres` to test internal DNS.
- **WebDAV 401/403:** Verify `readonly-bot` credentials in `.env` and that the user has access to the files in Nextcloud.
