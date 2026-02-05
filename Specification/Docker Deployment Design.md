 # Docker Deployment Design  
## Nextcloud AIO + Haystack RAG Stack (Event-Driven, Read-Only, ACL-Safe) with a Shared Reverse Proxy (Option 2A)

**Document version:** 1.0  
**Date:** 2026-02-04  
**Goal:** Run a complete system using Docker Compose with:
- **Nextcloud All-in-One (AIO)** as the document management system (DMS)
- A **Haystack-based RAG stack** (webhook gateway, workers, vector DB, metadata DB, API)
- A **shared reverse proxy** as a third Compose stack  
All components are connected via a **shared external Docker network**. The RAG stack is **read-only** towards Nextcloud and enforces **per-user access control** (ACL filtering).

---

## 1. Why Option 2A is the Best Fit

### 1.1 Nextcloud AIO is a “special” deployment model
Nextcloud AIO runs a **master container** that starts/manages multiple child containers via the **Docker socket**. Those child containers are not managed by `docker compose` in the same way as typical services. Splitting into separate stacks avoids lifecycle and naming conflicts.

### 1.2 Clean separation of concerns
- **Stack 1 (Proxy):** single TLS entry point, routing, certificates
- **Stack 2 (Nextcloud AIO):** Nextcloud and its managed child containers
- **Stack 3 (RAG):** ingestion + indexing + Q&A API

This keeps upgrades, restarts, troubleshooting, and backups simpler and more predictable.

### 1.3 Security & compliance
- Nextcloud remains the **source of truth** for documents and permissions.
- RAG services operate **read-only** via WebDAV.
- ACL filtering happens at **retrieval time** (vector DB filter), preventing data leakage to the LLM.

---

## 2. Target Architecture Overview

### 2.1 High-level component diagram
```
                 ┌─────────────────────────────────────────────────────┐
                 │                     Internet                         │
                 └───────────────┬─────────────────────────────────────┘
                                 │ HTTPS (443)
                         ┌───────▼────────┐
                         │ Reverse Proxy  │  (Traefik/Caddy/Nginx)
                         └───────┬────────┘
          ┌──────────────────────┼───────────────────────────┐
          │                      │                           │
  cloud.example.com       rag.example.com             (optional paths)
          │                      │
┌─────────▼─────────┐   ┌────────▼──────────┐
│ Nextcloud AIO      │   │ Haystack API      │
│ (master + children)│   │ + RAG stack       │
└─────────┬─────────┘   └────────┬──────────┘
          │                       │
          │ Webhooks              │ WebDAV (read-only)
          │ (events)              │ (file reads)
          ▼                       ▼
  Webhook Gateway  ───────►  Indexer / ACL Workers ───► Qdrant + Postgres
```

### 2.2 Core properties
- **Event-driven ingestion:** Nextcloud triggers webhook events to the gateway.
- **Read-only:** RAG stack reads documents via WebDAV; no writes to Nextcloud.
- **ACL-safe:** User queries are filtered by user/group permissions at retrieval time.

---

## 3. Deployment Layout (Recommended Folder Structure)

```
/docker-deploy
  /proxy
    docker-compose.yml
    .env
  /nextcloud-aio
    docker-compose.yml
    .env
  /rag-stack
    docker-compose.yml
    .env
  README.md
```

---

## 4. Shared External Docker Network

### 4.1 Create the network once
Run once on the host:

```bash
docker network create platform-net
```

### 4.2 Use `platform-net` in all compose files
Each Compose stack should attach its services to this network:

```yaml
networks:
  platform-net:
    external: true
```

And for services:

```yaml
services:
  some-service:
    networks:
      - platform-net
```

---

## 5. Domain / Routing Strategy

### 5.1 Recommended: Subdomains
- `cloud.example.com` → Nextcloud
- `rag.example.com` → Haystack API (chat/search)
- optional: `cloud.example.com/webhook/nextcloud` → Webhook Gateway (if you prefer same domain)

**Why subdomains?**  
They are simpler to route, reduce path conflicts, and avoid tricky rewrites for Nextcloud.

### 5.2 TLS
Let the reverse proxy manage:
- certificates (Let’s Encrypt)
- redirects HTTP→HTTPS
- HSTS (optional)

---

## 6. Stack 1: Reverse Proxy (Concept)

### 6.1 Responsibilities
- Terminate TLS (443)
- Route requests by hostname (and/or path)
- Provide a single public entry point

### 6.2 Routing rules (conceptual)
- If `Host == cloud.example.com` → forward to Nextcloud (AIO endpoint)
- If `Host == rag.example.com` → forward to `haystack-api:8000`
- If `Host == cloud.example.com` and `Path startswith /webhook/nextcloud` → forward to `webhook-gateway:8080`

---

## 7. Stack 2: Nextcloud AIO (Concept)

### 7.1 Key characteristics
- The AIO **master container** must have access to:
  - Docker socket: `/var/run/docker.sock`
  - a persistent volume for AIO config/state
- AIO manages its own DB/redis/nextcloud containers internally.

### 7.2 Reverse proxy mode
Run AIO in a mode compatible with an external reverse proxy.  
Practical outcome:
- Nextcloud is accessible at `https://cloud.example.com`
- Internal routing from proxy to AIO/Nextcloud is stable

### 7.3 Required setup inside Nextcloud
1. **Create a read-only service account** (e.g. `readonly-bot`)
2. Assign **read-only access** to the folders that should be searchable
   - user home folders (if intended)
   - shared folders / group folders (if intended)
3. Create an **App Password** for WebDAV access (recommended)

---

## 8. Stack 3: RAG Stack (Haystack + Ingestion)

### 8.1 Services (recommended)
- `webhook-gateway` (FastAPI)
- `redis` (queue)
- `indexer-worker` (content ingestion)
- `acl-worker` (permission updates + reconcile)
- `qdrant` (vector DB)
- `postgres` (metadata store)
- `haystack-api` (application-facing Q&A API)
- `ollama` or `local-ai` (optional, for on-prem LLM inference in future implementations)

### 8.2 Read-only WebDAV access
Indexer downloads files via:

```
https://cloud.example.com/remote.php/dav/files/readonly-bot/<path>
```

The RAG stack must never write to Nextcloud.

### 8.3 Event-driven ingestion
Nextcloud sends webhook events to:

- Internal (if routed via proxy):  
  `https://cloud.example.com/webhook/nextcloud`
- Or dedicated domain:  
  `https://rag.example.com/webhook/nextcloud`

Gateway validates events and enqueues jobs to Redis.

### 8.4 ACL-safety model (single index with query-time filters)
Each indexed chunk stores ACL metadata:
- `owner`
- `allowed_users[]`
- `allowed_groups[]`

At query time, Haystack applies this filter:
- allow if `owner == user`
- or `user ∈ allowed_users`
- or `allowed_groups ∩ user_groups ≠ ∅`

This prevents leakage *before* the LLM sees any content.

### 8.5 Handling permission changes reliably
Permission changes do not always produce file content changes. Therefore:
- process share/permission events if available
- also run an **ACL reconcile** periodically (e.g., every 10–30 minutes) to refresh ACL payload

---

## 9. Operational Workflows

### 9.1 Start order (first-time)
1. Create network: `docker network create platform-net`
2. Start proxy stack
3. Start Nextcloud AIO stack and complete initial setup in the AIO UI
4. Configure DNS: `cloud.example.com`, `rag.example.com`
5. Configure Nextcloud:
   - `readonly-bot`
   - app password
   - workflow/webhook to gateway
6. Start RAG stack
7. Verify:
   - file upload triggers indexing
   - queries return only allowed results

### 9.2 Day-2 operations
- Update Nextcloud via AIO update mechanism
- Update RAG stack via `docker compose pull && docker compose up -d`
- Backups:
  - AIO has its own backup approach
  - RAG stack: backup Qdrant volume + Postgres volume

---

## 10. Security Checklist

- Webhook endpoint protected by:
  - HMAC signature validation **and/or**
  - IP allowlist (if feasible)
- All external traffic over HTTPS only
- Read-only bot user:
  - minimal permissions
  - app password only
- Haystack API:
  - require authentication (OIDC bearer token)
  - validate OIDC token (Issuer, Audience) against IdP
  - never accept user_id/groups from the client without verification
- Retrieval-level ACL filtering enforced server-side

---

## 11. Minimal Acceptance Tests

1. **Event-driven indexing:** Upload a PDF → searchable within configured time.
2. **User isolation:** User A cannot retrieve content from User B’s private folder.
3. **Shared access:** User A can retrieve shared content; removing share removes visibility after ACL update/reconcile.
4. **Read-only guarantee:** No Nextcloud writes from RAG stack.
5. **Citations:** Responses include Nextcloud path and page when available.

---

## 12. Notes and Recommendations

- Prefer **subdomains** for clean routing and fewer Nextcloud path edge cases.
- Keep **AIO** as a dedicated stack; do not attempt to manually manage its child containers.
- Use a **single vector index** with payload ACL filters for scalable permission handling.
- Keep the webhook gateway internal if possible; expose only what’s required.

---

## 13. Next Implementation Deliverables (if you want them)
- Copy/paste-ready Compose files:
  - `/proxy/docker-compose.yml` (Traefik or Caddy)
  - `/nextcloud-aio/docker-compose.yml`
  - `/rag-stack/docker-compose.yml` (include OIDC env vars for API)
- Example webhook payload (mapped to specific NC Webhook App) + HMAC verification
- Qdrant payload schema + filter examples
- Haystack pipeline configuration for `/chat` with sources
