from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from src.main.repo.mongodb_repo import MongoDBRepo, RepoOperationError, DBConnectionError

router = APIRouter()

COLLECTION = "document_chunks"


def get_repo() -> MongoDBRepo:
    return MongoDBRepo()


def _serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if doc is None:
        return doc
    _id = doc.get("_id")
    if _id is not None:
        doc = dict(doc)
        doc["_id"] = str(_id)
    return doc


class DocumentChunk(BaseModel):
    document_id: str
    chunk_id: str
    content: str
    metadata: Optional[Dict[str, Any]] = None


@router.post("/chunks")
def create_chunk(chunk: DocumentChunk):
    repo = get_repo()
    try:
        inserted_id = repo.store(COLLECTION, chunk.dict())
        return {"inserted_id": str(inserted_id)}
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str):
    repo = get_repo()
    try:
        doc = repo.retrieve(COLLECTION, {"chunk_id": chunk_id})
        if not doc:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return _serialize_doc(doc)
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chunks")
def list_chunks(
    document_id: Optional[str] = Query(None, description="Filter by parent document_id"),
    limit: int = Query(50, ge=1, le=500),
):
    repo = get_repo()
    try:
        query: Dict[str, Any] = {"document_id": document_id} if document_id else {}
        results = repo.search(COLLECTION, query=query, limit=limit)
        return [_serialize_doc(d) for d in results]
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/chunks/{chunk_id}")
def delete_chunk(chunk_id: str):
    repo = get_repo()
    try:
        deleted = repo.delete(COLLECTION, {"chunk_id": chunk_id})
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return {"deleted": deleted}
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))
