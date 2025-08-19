from __future__ import annotations

from fastapi import FastAPI

from src.main.api.document_chunks_api import router as chunks_router
from src.main.api.document_metadata_api import router as docs_router
from src.main.api.embeddings_api import router as embeds_router
from src.main.api.ingest_api import router as ingest_router
from src.main.repo.mongodb_repo import MongoDBRepo
import pymongo

app = FastAPI(title="GenAI Hack API", version="1.0.0")

# Include routers
app.include_router(ingest_router, tags=["ingest"])
app.include_router(docs_router, tags=["documents"])
app.include_router(chunks_router, tags=["chunks"])
app.include_router(embeds_router, tags=["embeddings"])


@app.on_event("startup")
def create_indexes():
    """Create basic indexes to ensure uniqueness and query performance."""
    repo = MongoDBRepo()
    try:
        # document_metadata: unique document_id
        repo.create_index("document_metadata", [("document_id", pymongo.ASCENDING)], unique=True)
        # document_chunks: document_id + chunk_index, chunk_id unique
        repo.create_index("document_chunks", [("chunk_id", pymongo.ASCENDING)], unique=True)
        repo.create_index("document_chunks", [("document_id", pymongo.ASCENDING), ("chunk_index", pymongo.ASCENDING)], unique=False)
        # embeddings: embedding_id unique, document_chunk_id query
        repo.create_index("embeddings", [("embedding_id", pymongo.ASCENDING)], unique=True)
        repo.create_index("embeddings", [("document_chunk_id", pymongo.ASCENDING)], unique=False)
    except Exception:
        # Index creation failures shouldn't block the app; logs are handled inside repo
        pass
