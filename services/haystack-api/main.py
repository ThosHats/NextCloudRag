import os
import logging
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from src.pipeline import RagPipeline

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("haystack-api")

app = FastAPI(title="Nextcloud RAG API")
security = HTTPBearer()

# Initialize Pipeline (Lazy load might be better, but global for simplicity)
try:
    rag_pipeline = RagPipeline()
    logger.info("RAG Pipeline initialized.")
except Exception as e:
    logger.error(f"Failed to initialize RAG Pipeline: {e}")
    rag_pipeline = None

# OIDC Configuration
OIDC_ISSUER = os.getenv("OIDC_ISSUER")
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID")

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

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Mockable Token Verification.
    In prod, using python-jose to verify JWT against OIDC_ISSUER jwks.json.
    """
    token = credentials.credentials
    if not OIDC_ISSUER:
        # Dev mode / No auth configured
        logger.warning("OIDC_ISSUER not set, skipping token verification (DEV MODE)")
        return {"sub": "dev-user", "roles": ["admin"]}
    
    # Placeholder for real JWT verification logic
    # try:
    #     header = jwt.get_unverified_header(token)
    #     ... verify signature ...
    # except ...
    
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
