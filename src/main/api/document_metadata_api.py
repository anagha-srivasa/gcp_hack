from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, Optional, List
from src.main.repo.mongodb_repo import MongoDBRepo, RepoOperationError, DBConnectionError

router = APIRouter()

COLLECTION = "document_metadata"


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


class DocumentMetadata(BaseModel):
    document_id: str
    title: str
    author: Optional[str] = None
    created_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/documents")
def create_document(doc: DocumentMetadata):
    repo = get_repo()
    try:
        inserted_id = repo.store(COLLECTION, doc.dict())
        return {"inserted_id": str(inserted_id)}
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    repo = get_repo()
    try:
        result = repo.retrieve(COLLECTION, {"document_id": document_id})
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")
        return _serialize_doc(result)
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents")
def list_documents(author: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=500)):
    repo = get_repo()
    try:
        query: Dict[str, Any] = {"author": author} if author else {}
        results = repo.search(COLLECTION, query=query, limit=limit)
        return [_serialize_doc(d) for d in results]
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{document_id}")
def delete_document(document_id: str):
    repo = get_repo()
    try:
        deleted = repo.delete(COLLECTION, {"document_id": document_id})
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"deleted": deleted}
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))
