from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from src.main.repo.mongodb_repo import MongoDBRepo, RepoOperationError, DBConnectionError

router = APIRouter()

COLLECTION = "embeddings"


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


class Embedding(BaseModel):
    embedding_id: str
    document_chunk_id: str
    embedding_vector: List[float]
    metadata: Optional[Dict[str, Any]] = None


@router.post("/embeddings")
def create_embedding(embedding: Embedding):
    repo = get_repo()
    try:
        inserted_id = repo.store(COLLECTION, embedding.dict())
        return {"inserted_id": str(inserted_id)}
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/embeddings/{embedding_id}")
def get_embedding(embedding_id: str):
    repo = get_repo()
    try:
        result = repo.retrieve(COLLECTION, {"embedding_id": embedding_id})
        if not result:
            raise HTTPException(status_code=404, detail="Embedding not found")
        return _serialize_doc(result)
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/embeddings")
def list_embeddings(
    chunk_id: Optional[str] = Query(None, alias="document_chunk_id"),
    limit: int = Query(50, ge=1, le=500),
):
    repo = get_repo()
    try:
        query: Dict[str, Any] = {"document_chunk_id": chunk_id} if chunk_id else {}
        results = repo.search(COLLECTION, query=query, limit=limit)
        return [_serialize_doc(d) for d in results]
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/embeddings/{embedding_id}")
def delete_embedding(embedding_id: str):
    repo = get_repo()
    try:
        deleted = repo.delete(COLLECTION, {"embedding_id": embedding_id})
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Embedding not found")
        return {"deleted": deleted}
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))
