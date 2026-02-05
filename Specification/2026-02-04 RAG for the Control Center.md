# Requirements & Functional Specification  
## Nextcloud + Haystack (RAG) Integration — Event‑Driven, Read‑Only, ACL‑Safe

**Document version:** 1.0  
**Date:** 2026-02-04  
**Audience:** Product, Engineering, IT/Infrastructure, Quality Management (QM)  
**Scope:** Integrate document-centric Q&A (“NotebookLM-like”) capabilities into an application by combining **Nextcloud** as the document source/DMS and **Haystack** as the Retrieval‑Augmented Generation (RAG) framework, using an **event-driven** and **read-only** ingestion model, with **strict access control** (ACL filtering).

---

## 1. Goal and Desired Outcome

### 1.1 Business Goal
Provide users with a secure, intuitive way to ask questions and receive answers **grounded in the documents they are allowed to access in Nextcloud**, including shared folders, without exposing documents outside their permissions.

### 1.2 What “Success” Looks Like
- Users can **upload and manage documents in Nextcloud** as they do today.
- The application offers a **chat / Q&A interface** that answers questions based on those documents.
- Results and citations only come from:
  - the user’s own Nextcloud space (home directory), and
  - shared folders/files that the user has explicit access to.
- The system remains **read-only** towards Nextcloud (no writing back, no altering metadata).
- Indexing is **event-driven** (near-real-time updates after uploads/changes).
- The system is **audit-friendly** (traceable sources, predictable data flows, minimal duplication).

---

## 2. High-Level Requirements

### 2.1 Functional Requirements (FR)
**FR-01 Document Discovery (Read-only)**  
The system shall read documents from Nextcloud using read-only access.

**FR-02 Event-Driven Indexing**  
The system shall update its index based on Nextcloud events (create/update/move/delete).

**FR-03 Supported Document Types**  
The system shall ingest at minimum: PDF (text-based), DOCX, TXT, Markdown.  
Optional: HTML, CSV, JSON.  
Scanned PDFs shall be supported via optional OCR.

**FR-04 Chunking & Embeddings**  
The system shall split documents into searchable chunks and store embeddings and metadata for retrieval.

**FR-05 ACL-Safe Retrieval**  
The system shall ensure that retrieval results for a user only contain chunks from documents the user can access in Nextcloud.

**FR-06 Shared Folders / Group Folders**  
The system shall support shared documents and group folders, reflecting Nextcloud permissions.

**FR-07 Citations / References**  
The system shall return citations referencing the original document location in Nextcloud (e.g., path, file id, page).

**FR-08 Deletion Handling**  
The system shall remove or deactivate indexed content when a file is deleted or access is revoked.

**FR-09 Search & Chat Interface**  
The system shall expose an API for:
- chat/Q&A with sources,
- search (optional),
- document/source listing (optional).

**FR-10 Multitenancy / User Isolation**  
The system shall enforce isolation per user via query-time ACL filters.

### 2.2 Non-Functional Requirements (NFR)
**NFR-01 Read-only to Nextcloud**  
No writes to Nextcloud (no tagging, no metadata modification, no file changes).

**NFR-02 Security & Compliance**  
- Strong authentication for users (e.g., OIDC/OAuth via IdP/Nextcloud).
- Server-side authorization and filtering.
- Encryption in transit (TLS) and at rest (where applicable).

**NFR-03 Performance**  
- Event-to-index latency target: configurable, typically seconds to a few minutes.
- Retrieval latency: interactive (typically < 2–5 seconds depending on LLM).

**NFR-04 Scalability**  
Support up to ~200 reviewers/users and organization-wide document sets by using a single index with metadata filters.

**NFR-05 Observability**  
Logging and metrics for ingestion, indexing, query performance, and access-filter correctness.

**NFR-06 Reliability**  
Queue-based processing; ingestion retries; idempotent indexing operations.

**NFR-07 Auditability**  
Maintain traceability:
- “Which document chunks contributed to an answer?”
- “Which version/etag/hash was indexed?”

---

## 3. Constraints & Assumptions

- Nextcloud is the authoritative source of truth for files and permissions.
- The integration must work **on-prem** (self-hosted) and be containerized (Docker).
- The LLM may be external (Gemini/OpenAI) or local; the architecture must allow swapping providers.
- The organization expects a workflow compatible with ISO-style traceability and controlled document access.

---

## 4. Proposed Solution (Recommended Architecture)

### 4.1 Summary
Use a **single vector index** (e.g., Qdrant) storing document chunks + embeddings + ACL metadata, and enforce permissions via **query-time filtering**.  
Indexing and ACL updates are triggered **event-driven** by Nextcloud webhooks (where possible), complemented by an **ACL reconcile job** to remain robust when permission changes occur without a file edit.

### 4.2 Components (Containerized)
1. **Webhook Gateway (FastAPI)**  
   - Receives Nextcloud events (HTTP POST) from the **Nextcloud Webhooks App** (or Workflow script)
   - Verifies authenticity (HMAC shared secret)
   - Pushes jobs to a queue (Redis)

2. **Queue (Redis)**  
   - Buffers jobs; enables retries and decoupling

3. **Indexer Worker**  
   - Pulls file content read-only via WebDAV
   - Extracts text (and OCR if configured)
   - Chunks content and generates embeddings
   - Upserts chunks into Vector DB with metadata + ACL payload
   - Updates metadata store (Postgres)

4. **ACL Worker (Reconcile + Event-driven ACL updates)**  
   - Updates ACL payload for documents/chunks without re-embedding
   - Handles “share changed” events if available
   - Periodic reconcile to ensure correctness

5. **Vector DB (Qdrant)**  
   - Stores embeddings + payload filters for ACL-safe retrieval

6. **Metadata DB (Postgres)**  
   - Tracks files (file_id/path), etag/hash, indexing status, timestamps
   - Supports idempotency and reconciliation

7. **Haystack API Service**  
   - Exposes `/chat` and optionally `/search`
   - Performs retrieval with ACL filters
   - Calls the configured LLM
   - Returns answer + sources (citations)

---

## 5. Detailed Functional Specification

### 5.1 Data Flow

#### 5.1.1 Document Upload / Update (Event-Driven)
1. User uploads or updates a document in Nextcloud (home folder or shared folder).
2. Nextcloud triggers a workflow event (via **Webhooks App**) to the **Webhook Gateway** (HTTP POST).
3. Gateway validates the webhook (HMAC) and enqueues a **content job**.
4. Indexer Worker fetches the file read-only via WebDAV.
5. Worker extracts text, chunks, embeds, and upserts to Qdrant with metadata and ACL.
6. Metadata DB is updated with `file_id`, `etag/hash`, `indexed_at`.

**Expected result:** The document becomes searchable within minutes (often seconds).

#### 5.1.2 Permission Changes (ACL Updates)
Permission changes may not always trigger file content changes. Therefore:
- If Nextcloud can emit share/permission events, Gateway enqueues an **ACL job**.
- Additionally, ACL Worker runs a periodic reconcile (e.g., every 10–30 minutes):
  - checks known files and refreshes ACL state from Nextcloud (read-only),
  - updates only ACL payload in Qdrant.

**Expected result:** Users immediately stop seeing results when access is revoked (event-driven), or within the reconcile interval as a safety net.

#### 5.1.3 Query / Chat
1. User authenticates to the application (OIDC/OAuth).
2. Application obtains `user_id` and `group_ids` (claims or lookup).
3. Client calls `POST /chat` with query.
4. Haystack API builds an ACL filter and retrieves only allowed chunks.
5. LLM generates an answer from retrieved chunks.
6. API returns:
   - answer text
   - citations (Nextcloud path, page, snippet id)

---

### 5.2 APIs

#### 5.2.1 Webhook Gateway (internal)
`POST /webhook/nextcloud`

**Note:** The payload structure below is generic. The actual implementation must match the JSON output of the chosen Nextcloud Webhooks App (e.g., *nc-webhook*, *flow_notifications*, or a custom *Workflow* script).

**Headers**
- `X-Signature`: HMAC SHA-256 over request body

**Body (minimum)**
```json
{
  "event": "file.updated",
  "path": "/QM/ISO9001/VA-007.pdf",
  "file_id": "123456",
  "etag": ""a1b2c3""
}
```

Supported events:
- `file.created`, `file.updated`, `file.moved`, `file.deleted`
- `acl.changed` (if available)

#### 5.2.2 Haystack API (application-facing)
`POST /chat`

**Request**
```json
{
  "query": "What does the procedure require for document approval?",
  "conversation_id": "optional",
  "top_k": 8
}
```

**Response**
```json
{
  "answer": "…",
  "sources": [
    {
      "title": "VA-007.pdf",
      "nc_path": "/QM/ISO9001/VA-007.pdf",
      "page": 4,
      "chunk_id": "…",
      "confidence": 0.78
    }
  ]
}
```

Optionally:
- `POST /search`
- `GET /sources` (user-scoped)

---

### 5.3 Index Data Model

#### 5.3.1 Vector Payload (Qdrant)
Per chunk:
- `nc_file_id` (string)
- `nc_path` (string)
- `etag` or `sha256` (string)
- `page` (int, optional)
- `chunk_id` (string)
- `title` (string)

ACL:
- `owner` (string)
- `allowed_users` (string array)
- `allowed_groups` (string array)

Optional:
- `status` (draft/released/obsolete)
- `folder_type` (home/share/groupfolder)

#### 5.3.2 Metadata Store (Postgres)
Tables (conceptual):
- `files(file_id, path, etag, sha256, last_seen, last_indexed, status)`
- `acl(file_id, owner, allowed_users, allowed_groups, acl_updated)`
- `jobs(job_id, type, file_id, status, attempts, created_at, updated_at)`

---

### 5.4 ACL Enforcement (Core Rule)
For user `U` with groups `G`, retrieval must apply:

**Allow if:**
- `owner == U` **OR**
- `U ∈ allowed_users` **OR**
- `allowed_groups ∩ G ≠ ∅`

This filtering happens at the **retrieval layer** (Vector DB filter), not by post-processing, to avoid leakage.

---

### 5.5 Supported Document Handling

#### 5.5.1 PDFs
- Text-based PDFs: extract text directly.
- Scanned PDFs: optional OCR step before chunking.

#### 5.5.2 DOCX / Markdown / TXT
- Extract textual content.
- Preserve basic structure (headings) if possible for better chunking.

#### 5.5.3 Tables and Images
- Complex layout tables may require specialized parsing; initial version treats them as text where possible.
- Images require OCR to become searchable.

---

### 5.6 Deletion & Revocation
- On `file.deleted`: remove (hard delete) or mark inactive (soft delete) in Vector DB and metadata store.
- On access revocation: update ACL payload so the user no longer retrieves those chunks.

---

## 6. Why This Solution Is the Best Fit

### 6.1 Best Match for Nextcloud Permission Model
Nextcloud uses per-user home directories plus flexible sharing. A **single index with ACL filtering** mirrors this naturally:
- Shared folders are just documents with broader ACL sets.
- No duplication required for each user.

### 6.2 Security: “No Leakage by Design”
Filtering at retrieval ensures:
- The LLM never sees unauthorized chunks.
- Prompt tricks cannot retrieve inaccessible documents.

### 6.3 Operational Simplicity & Scalability
Compared to “one index per user”:
- Fewer moving parts (one collection, one pipeline).
- Efficient for hundreds of users and shared spaces.
- Centralized monitoring and backup.

### 6.4 Read-only Compliance & Auditability
- Nextcloud remains authoritative (no writes).
- Metadata store and vector payload provide traceability (file_id, etag/hash, page).
- Suitable for ISO/QMS workflows where evidence and controlled access matter.

### 6.5 Event-driven Responsiveness + Robustness
- Events provide near real-time indexing.
- Periodic ACL reconcile prevents edge-case drift (permission changes without file changes).

---

## 7. Deployment (Docker) — Reference Topology

### 7.1 Services
- `webhook-gateway` (FastAPI)
- `redis`
- `indexer-worker`
- `acl-worker`
- `qdrant`
- `postgres`
- `haystack-api`

### 7.2 Configuration (Environment)
- Nextcloud WebDAV base URL (read-only bot)
- App password / token for WebDAV (read-only)
- HMAC secret for webhook validation
- Chunk sizes, overlap, OCR on/off
- Vector DB endpoints
- LLM provider configuration
- **Authentication (OIDC):**
  - OIDC Issuer URL
  - Client ID
  - Audience / Scopes

### 7.3 Read-only Service Account
Create `readonly-bot` with:
- read access to intended folders
- no write permissions
- app password for service authentication

---

## 8. Acceptance Criteria (Testable)

1. **User isolation:**  
   User A cannot retrieve sources belonging only to User B.

2. **Shared folder visibility:**  
   If a file is shared with User A, A can retrieve it; if unshared, A cannot retrieve it after ACL update/reconcile.

3. **Event indexing:**  
   Upload/update triggers indexing and becomes searchable within configured latency.

4. **Citations:**  
   Every answer includes at least one citation when sourced from documents; citations reference Nextcloud paths/pages.

5. **Read-only guarantee:**  
   No Nextcloud write operations occur from any service (validated via logs/config and permission setup).

6. **Resilience:**  
   Failed jobs retry and do not create duplicated chunks (idempotency via `file_id + etag/hash`).

---

## 9. Out of Scope (for v1)
- Full Nextcloud UI embedding (native Nextcloud app)
- Advanced layout preservation (complex tables, figures)
- Fine-grained sentence-level citations for every output token
- Cross-tenant federation across multiple Nextcloud instances

---

## 10. Implementation Notes (Recommended Defaults)

- Vector DB: **Qdrant** (excellent payload filtering, simple ops)
- Queue: **Redis**
- Metadata: **Postgres**
- OCR: optional (Tesseract or a dedicated OCR microservice)
- Chunking: `CHUNK_SIZE ~ 900 tokens`, `OVERLAP ~ 150 tokens` (tune based on docs)
- Reconcile: every 10–30 minutes (tune based on share-change frequency)

---

## Appendix A — Glossary

- **RAG:** Retrieval‑Augmented Generation (LLM answers grounded by retrieved documents)
- **ACL:** Access Control List (who can access what)
- **Chunk:** A piece of a document stored for retrieval (e.g., paragraph/section)
- **ETag:** Nextcloud/HTTP change marker
- **WebDAV:** Protocol for file access over HTTP used by Nextcloud

