"""
FastAPI Backend Application for DarGlobal + Wasalt Real Estate Chatbot
Provides REST and Server-Sent Events (SSE) streaming endpoints.
"""

import os
import sys
import re
import json
import time
import uuid
import asyncio
import logging
from pathlib import Path
from collections import defaultdict
from typing import Optional, List, Dict, Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import settings
from app.graph import run_chat
from app.vector_store import VectorStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("backend_api")

# -----------------------------------------------------------------------------
# FastAPI App Initialization
# -----------------------------------------------------------------------------
app = FastAPI(
    title="DarGlobal & Wasalt Real Estate AI Chatbot API",
    description="Production backend API powering the bilingual LangGraph RAG property advisor.",
    version="1.0.0"
)

# CORS Middleware (Allows frontend development on localhost and cross-origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# In-Memory Rate Limiter
# -----------------------------------------------------------------------------
class InMemoryRateLimiter:
    """Sliding-window IP rate limiter to guard against API abuse."""
    def __init__(self, max_requests: int = 120, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.clients = defaultdict(list)

    def is_rate_limited(self, client_ip: str) -> bool:
        now = time.time()
        timestamps = self.clients[client_ip]
        # Discard records outside current sliding window
        valid_timestamps = [t for t in timestamps if now - t < self.window_seconds]
        self.clients[client_ip] = valid_timestamps
        if len(valid_timestamps) >= self.max_requests:
            return True
        self.clients[client_ip].append(now)
        return False


rate_limiter = InMemoryRateLimiter(max_requests=120, window_seconds=60)


@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    """Enforce request limits per client IP."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    
    # Exclude internal health checks from aggressive rate limiting
    if request.url.path not in ("/health", "/docs", "/openapi.json"):
        if rate_limiter.is_rate_limited(client_ip):
            logger.warning(f"Rate limit exceeded for IP: {client_ip}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "message": "Too many requests. Please wait a moment before sending another query."
                }
            )
    return await call_next(request)


# -----------------------------------------------------------------------------
# Pydantic Schemas
# -----------------------------------------------------------------------------
class ChatRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=1500,
        description="User search query or conversational prompt"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier for multi-turn conversational memory"
    )
    language: Optional[str] = Field(
        default=None,
        description="Explicit user language preference ('en' or 'ar')"
    )


class ChatResponse(BaseModel):
    answer: str
    sources: List[Dict[str, str]]
    route: str
    session_id: str
    retrieved_count: int


# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------
@app.get("/health", tags=["System"])
async def health_check():
    """
    Health check endpoint reporting vector store count and LLM configuration status.
    """
    try:
        vs = VectorStore(
            persist_directory=settings.CHROMA_PERSIST_DIRECTORY,
            collection_name=settings.COLLECTION_NAME
        )
        vector_count = vs.count_documents()
    except Exception as e:
        logger.error(f"Error querying ChromaDB health: {e}")
        vector_count = 0

    return {
        "status": "healthy",
        "version": "1.0.0",
        "vector_count": vector_count,
        "collection_name": settings.COLLECTION_NAME,
        "llm": {
            "configured": settings.is_llm_configured(),
            "primary_model": settings.PRIMARY_MODEL,
            "fallback_model": settings.FALLBACK_MODEL,
        }
    }


@app.get("/sources", tags=["Data"])
async def get_indexed_sources():
    """
    Retrieve statistics and unique indexed projects and cities across DarGlobal and Wasalt.
    """
    try:
        vs = VectorStore(
            persist_directory=settings.CHROMA_PERSIST_DIRECTORY,
            collection_name=settings.COLLECTION_NAME
        )
        data = vs.collection.get(include=["metadatas"])
        metadatas = data.get("metadatas", [])

        darglobal_projects = set()
        darglobal_count = 0
        wasalt_cities = set()
        wasalt_types = set()
        wasalt_count = 0

        for meta in metadatas:
            src = meta.get("source", "").lower()
            if "darglobal" in src:
                darglobal_count += 1
                title = meta.get("title") or meta.get("project_name")
                if title:
                    darglobal_projects.add(title)
            elif "wasalt" in src:
                wasalt_count += 1
                city = meta.get("city")
                if city:
                    wasalt_cities.add(city)
                pt = meta.get("property_type")
                if pt:
                    wasalt_types.add(pt)

        return {
            "total_chunks": len(metadatas),
            "sources": {
                "darglobal": {
                    "chunks": darglobal_count,
                    "projects": sorted(list(darglobal_projects))
                },
                "wasalt": {
                    "chunks": wasalt_count,
                    "cities": sorted(list(wasalt_cities)),
                    "property_types": sorted(list(wasalt_types))
                }
            }
        }
    except Exception as e:
        logger.error(f"Error inspecting sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", tags=["Chat"])
async def stream_chat(request: ChatRequest):
    """
    Server-Sent Events (SSE) streaming endpoint.
    Emits real-time tokens, conversation metadata, and verified URL citations.
    """
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"

    async def event_generator():
        try:
            loop = asyncio.get_running_loop()

            # Execute LangGraph pipeline in worker thread to maintain non-blocking I/O
            result = await loop.run_in_executor(
                None,
                lambda: run_chat(query=request.query, thread_id=session_id)
            )

            # 1. Emit Metadata Event
            meta_data = {
                "type": "metadata",
                "route": result.get("route", "real_estate"),
                "session_id": session_id,
                "retrieved_count": result.get("retrieved_count", 0)
            }
            yield f"event: metadata\ndata: {json.dumps(meta_data)}\n\n"
            await asyncio.sleep(0.01)

            # 2. Stream Answer Content Tokens
            answer_text = result.get("answer", "")
            # Split by whitespace/words to emit readable token chunks
            chunks = re.split(r'(\s+)', answer_text)
            for chunk in chunks:
                if chunk:
                    token_data = {"type": "token", "token": chunk}
                    yield f"event: token\ndata: {json.dumps(token_data)}\n\n"
                    await asyncio.sleep(0.015)

            # 3. Emit Sources Event (Citations removed per DRG-16 directive)
            sources_data = {"type": "sources", "sources": []}
            yield f"event: sources\ndata: {json.dumps(sources_data)}\n\n"
            await asyncio.sleep(0.01)

            # 4. Emit Done Event
            done_data = {"type": "done", "status": "complete"}
            yield f"event: done\ndata: {json.dumps(done_data)}\n\n"

        except Exception as e:
            logger.error(f"Error in SSE streaming generator: {e}", exc_info=True)
            err_data = {"type": "error", "message": str(e)}
            yield f"event: error\ndata: {json.dumps(err_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/chat/sync", response_model=ChatResponse, tags=["Chat"])
async def sync_chat(request: ChatRequest):
    """
    Synchronous JSON endpoint returning full response and citations in a single payload.
    """
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    loop = asyncio.get_running_loop()
    
    result = await loop.run_in_executor(
        None,
        lambda: run_chat(query=request.query, thread_id=session_id)
    )

    return ChatResponse(
        answer=result.get("answer", ""),
        sources=result.get("sources", []),
        route=result.get("route", "real_estate"),
        session_id=session_id,
        retrieved_count=result.get("retrieved_count", 0)
    )


# -----------------------------------------------------------------------------
# Static Files Mounting for Frontend
# -----------------------------------------------------------------------------
# Mount built React frontend if present in frontend/dist
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists() and (frontend_dist / "index.html").exists():
    logger.info(f"Mounting built React frontend from {frontend_dist}")
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
else:
    @app.get("/", tags=["System"])
    async def root_fallback():
        return {
            "title": "DarGlobal & Wasalt Real Estate Chatbot API",
            "status": "online",
            "version": "1.0.0",
            "docs": "/docs",
            "endpoints": {
                "health": "/health",
                "sources": "/sources",
                "chat_stream": "/chat (POST, SSE)",
                "chat_sync": "/chat/sync (POST, JSON)"
            }
        }


@app.get("/ping")
def ping():
    return {"message": "pong", "status": "alive"}