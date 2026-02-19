import os
import logging
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.pipeline import RagPipeline

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("haystack-api")

app = FastAPI(title="Nextcloud RAG API")

# Serve Static Files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

# Allow missing token for dev mode (auto_error=False)
security = HTTPBearer(auto_error=False)

# Initialize Pipeline (Lazy load might be better, but global for simplicity)
try:
    rag_pipeline = RagPipeline()
    logger.info("RAG Pipeline initialized.")
except Exception as e:
    logger.error(f"Failed to initialize RAG Pipeline: {e}")
    rag_pipeline = None

# OIDC Configuration
OIDC_ISSUER = os.getenv("OIDC_ISSUER")
if OIDC_ISSUER == "none": OIDC_ISSUER = None

OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID")
if OIDC_CLIENT_ID == "none": OIDC_CLIENT_ID = None

class ChatRequest(BaseModel):
    query: str
    top_k: int = 5
    conversation_id: Optional[str] = None

class Source(BaseModel):
    title: str
    nc_path: str
    score: float

class ChatResponse(BaseModel):
    answer: str
    sources: List[Source] = []

def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)):
    """
    Mockable Token Verification.
    If OIDC_ISSUER is not set, we allow unauthenticated access (admin role).
    """
    # 1. Dev Mode / No Auth
    if not OIDC_ISSUER:
        # Check if token provided anyway? usually ignore.
        return {"sub": "anonymous-admin", "roles": ["admin"]}
    
    # 2. Auth Required but missing
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Verify Token (Placeholder)
    token = credentials.credentials
    # In prod: jwt.decode(token, ...)
    
    return {"sub": "user", "token_preview": token[:10] + "..."}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: dict = Depends(verify_token)):
    if not rag_pipeline:
        raise HTTPException(status_code=503, detail="RAG Pipeline not initialized")

    logger.info(f"Chat request from {user.get('sub')}: {request.query}")

    try:
        # TODO: Construct ACL filters based on user claims
        filters = None 
        
        result = rag_pipeline.run(request.query, top_k=request.top_k, filters=filters)
        
        # Hack to get documents: In a real implementation with Haystack 2, 
        # we might need to modify the pipeline to return retrieved documents 
        # or use `include_outputs_from={"retriever"}` in pipeline.run().
        
        # Recalling run with output inclusion to get sources
        full_result = rag_pipeline.pipeline.run(
            {
                "text_embedder": {"text": request.query},
                "retriever": {"top_k": request.top_k, "filters": filters},
                "prompt_builder": {"question": request.query}
            },
            include_outputs_from={"retriever"}
        )
        
        answer = full_result["generator"]["replies"][0]
        documents = full_result["retriever"]["documents"]
        
        sources = []
        for doc in documents:
            sources.append(Source(
                title=doc.meta.get("path", "Unknown").split("/")[-1],
                nc_path=doc.meta.get("path", ""),
                score=doc.score or 0.0
            ))

        return ChatResponse(answer=answer, sources=sources)

    except Exception as e:
        logger.error(f"Error during RAG processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    return {"status": "ok", "pipeline": "ready" if rag_pipeline else "failed"}
