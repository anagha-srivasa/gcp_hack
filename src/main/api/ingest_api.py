from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from bson import ObjectId
import gridfs

from src.main.doc_processor.processor import process_file
from src.main.repo.mongodb_repo import MongoDBRepo, RepoOperationError, DBConnectionError
from src.main.config import get as get_config
from src.main.query.queries import list_query_names, get_query_template, materialize_query


router = APIRouter()

DOCS_COLLECTION = "document_metadata"
CHUNKS_COLLECTION = "document_chunks"
EMBEDS_COLLECTION = "embeddings"


def get_repo() -> MongoDBRepo:
    return MongoDBRepo()


def _cascade_delete_document(repo: MongoDBRepo, document_id: str) -> Dict[str, Any]:
    """Internal helper to delete metadata, chunks, embeddings, and stored file for a document_id."""
    # Fetch metadata to find file_id
    meta = repo.retrieve(DOCS_COLLECTION, {"document_id": document_id})
    if not meta:
        return {"document_id": document_id, "deleted": {"metadata": 0, "chunks": 0, "embeddings": 0, "file": False}}

    # Delete chunks and collect their IDs
    chunks = repo.search(CHUNKS_COLLECTION, query={"document_id": document_id}, limit=None)  # type: ignore[arg-type]
    chunk_ids = [c.get("chunk_id") for c in chunks if c.get("chunk_id")]
    deleted_chunks = repo.delete(CHUNKS_COLLECTION, {"document_id": document_id})

    # Delete embeddings that point to those chunk_ids (if any)
    deleted_embeds = 0
    if chunk_ids:
        deleted_embeds = repo.delete(EMBEDS_COLLECTION, {"document_chunk_id": {"$in": chunk_ids}})

    # Delete original file from GridFS
    file_id = meta.get("file_id")
    file_deleted = False
    if file_id:
        fs = gridfs.GridFS(repo.db)
        try:
            fs.delete(ObjectId(file_id))
            file_deleted = True
        except Exception:
            file_deleted = False

    # Finally delete metadata
    deleted_meta = repo.delete(DOCS_COLLECTION, {"document_id": document_id})

    return {
        "document_id": document_id,
        "deleted": {
            "metadata": deleted_meta,
            "chunks": deleted_chunks,
            "embeddings": deleted_embeds,
            "file": file_deleted,
        },
    }


@router.post("/ingest/upload")
async def ingest_upload(
    file: UploadFile = File(..., description="Drop a DOC/DOCX/PDF here"),
    document_id: Optional[str] = Form(None, description="Override auto-generated document_id"),
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    tags: Optional[str] = Form(None, description="Comma-separated tags"),
):
    """
    Upload a document (doc/docx/pdf), save original file to GridFS, extract & sectionize,
    then persist document metadata and section-chunks into MongoDB.
    """
    # Persist upload to a temp file so the processor can sniff and read it
    try:
        suffix = os.path.splitext(file.filename or "")[1] or ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            content = await file.read()
            tmp.write(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to buffer upload: {e}")

    # Generate or use provided document_id
    doc_id = document_id or f"doc_{uuid.uuid4().hex}"

    try:
        repo = get_repo()
        # Save original file in GridFS
        fs = gridfs.GridFS(repo.db)
        file_id = fs.put(
            content,
            filename=file.filename or doc_id,
            contentType=file.content_type or None,
            document_id=doc_id,
        )

        # Run the existing pipeline
        result = process_file(doc_id, tmp_path)

        # Build document metadata record
        size_bytes = os.path.getsize(tmp_path)
        tags_list: List[str] = [t.strip() for t in (tags.split(",") if tags else []) if t.strip()]
        doc_meta: Dict[str, Any] = {
            "document_id": doc_id,
            "title": title or (file.filename or doc_id),
            "description": "",
            "filename": file.filename or os.path.basename(tmp_path),
            "upload_date": datetime.utcnow().isoformat() + "Z",
            "author": author or "",
            "tags": tags_list,
            "num_chunks": len(result.sections),
            "size_bytes": int(size_bytes),
            "content_type": result.mime,
            "file_id": str(file_id),
        }

        # Store document metadata
        doc_inserted_id = repo.store(DOCS_COLLECTION, doc_meta)

        # Build and store chunk docs from sections with configurable chunking
        def _chunk_text(text: str, max_chars: int, overlap: int) -> List[str]:
            if max_chars <= 0:
                return [text]
            chunks: List[str] = []
            start = 0
            n = len(text)
            while start < n:
                end = min(n, start + max_chars)
                # try not to break in the middle of a word
                if end < n:
                    space = text.rfind(" ", start, end)
                    if space != -1 and space > start + int(0.5 * max_chars):
                        end = space
                chunks.append(text[start:end].strip())
                if end >= n:
                    break
                # move start with overlap
                start = max(0, end - max(0, overlap))
                if start == end:  # avoid infinite loop on tiny max/overlap
                    start += 1
            return [c for c in chunks if c]

        max_chars = int(get_config("processing.chunk.max_chars", 1500))
        overlap_chars = int(get_config("processing.chunk.overlap_chars", 200))

        chunk_docs: List[Dict[str, Any]] = []
        running_index = 0
        for sec in result.sections:
            # Combine title + text as the source content
            base_text = (sec.title + "\n\n" + sec.text).strip() if sec.text else sec.title
            pieces = _chunk_text(base_text, max_chars=max_chars, overlap=overlap_chars)
            for j, piece in enumerate(pieces):
                running_index += 1
                chunk_docs.append(
                    {
                        "document_id": doc_id,
                        "chunk_id": f"{sec.section_id}_c{j+1}",
                        "chunk_index": running_index - 1,
                        "content": piece,
                        "metadata": {
                            "level": sec.level,
                            "title": sec.title,
                            "page_start": sec.page_start,
                            "page_end": sec.page_end,
                            "related": sec.related or {},
                        },
                    }
                )

        inserted_chunk_ids: List[Any] = []
        if chunk_docs:
            # Bulk insert returns list of ObjectIds
            inserted_chunk_ids = repo.store(CHUNKS_COLLECTION, chunk_docs)  # type: ignore[assignment]

        return {
            "document_id": doc_id,
            "mime": result.mime,
            "document_inserted_id": str(doc_inserted_id),
            "chunks_inserted": len(inserted_chunk_ids) if chunk_docs else 0,
            "sections": len(result.sections),
            "chunks": len(chunk_docs),
            "file_id": str(file_id),
        }
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@router.get("/ingest/documents/search")
def search_documents(
    title: Optional[str] = Query(None),
    author: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    repo = get_repo()
    try:
        query: Dict[str, Any] = {}
        if title:
            query["title"] = {"$regex": title, "$options": "i"}
        if author:
            query["author"] = {"$regex": author, "$options": "i"}
        if tag:
            query["tags"] = tag
        docs = repo.search(DOCS_COLLECTION, query=query, limit=limit)
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return docs
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingest/documents/search/options")
def search_options():
    """List available search queries and their expected inputs for UI/dropdown wiring."""
    names = list_query_names()
    out = []
    for n in names:
        tmpl = get_query_template(n)
        out.append({"name": n, "description": tmpl.get("description", ""), "expects": tmpl.get("expects", [])})
    return out


@router.post("/ingest/documents/search/by-query")
def search_documents_by_named_query(
    name: str = Query(..., description="Select which predefined query to run"),
    params: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = Query(50, ge=1, le=500, description="Max docs to return"),
):
    """
    Search documents by selecting a predefined query (dropdown) and supplying its inputs.
    - name: one of the values from GET /ingest/documents/search/options
    - params: key/value inputs required by the selected query
    - limit: optional cap on results
    """
    params = params or {}
    try:
        query = materialize_query(name, params)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown query name")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid params: {e}")

    repo = get_repo()
    try:
        docs = repo.search(DOCS_COLLECTION, query=query, limit=limit)
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return docs
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingest/documents/{document_id}/file")
def fetch_document_file(document_id: str):
    repo = get_repo()
    try:
        meta = repo.retrieve(DOCS_COLLECTION, {"document_id": document_id})
        if not meta:
            raise HTTPException(status_code=404, detail="Document not found")
        file_id = meta.get("file_id")
        if not file_id:
            raise HTTPException(status_code=404, detail="Original file not stored")

        fs = gridfs.GridFS(repo.db)
        gridout = fs.get(ObjectId(file_id))

        def file_iterator(chunk_size: int = 8192):
            while True:
                chunk = gridout.read(chunk_size)
                if not chunk:
                    break
                yield chunk

        media_type = meta.get("content_type") or gridout.content_type or "application/octet-stream"
        filename = meta.get("filename") or gridout.filename or f"{document_id}"
        return StreamingResponse(
            file_iterator(),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
        )
    except gridfs.NoFile:
        raise HTTPException(status_code=404, detail="File not found in storage")
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/ingest/documents/{document_id}")
def delete_document_cascade(document_id: str):
    """Delete metadata, chunks, embeddings, and the stored original file."""
    repo = get_repo()
    try:
        meta = repo.retrieve(DOCS_COLLECTION, {"document_id": document_id})
        if not meta:
            raise HTTPException(status_code=404, detail="Document not found")
        return _cascade_delete_document(repo, document_id)
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


class DeleteParams:
    """Schema helper for FastAPI docs: shows dropdown of available queries and required inputs."""
    # Not using Pydantic to keep it simple and flexible for dynamic params.
    pass


@router.get("/ingest/documents/delete/options")
def delete_options():
    """List available delete queries and their expected inputs for UI/dropdown wiring."""
    names = list_query_names()
    out = []
    for n in names:
        tmpl = get_query_template(n)
        out.append({"name": n, "description": tmpl.get("description", ""), "expects": tmpl.get("expects", [])})
    return out


@router.post("/ingest/documents/delete/by-query")
def delete_documents_by_named_query(
    name: str = Query(..., description="Select which predefined query to run"),
    params: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = Query(None, ge=1, description="Max matched docs to delete"),
    dry_run: bool = Query(False, description="List matches without deleting"),
):
    """
    Delete documents by selecting a predefined query (dropdown) and supplying its inputs.
    - name: one of the values from GET /ingest/documents/delete/options
    - params: key/value inputs required by the selected query
    - limit: optional cap on matched documents
    - dry_run: if true, returns matched document_ids only
    """
    params = params or {}
    try:
        # Materialize Mongo query from template + params
        query = materialize_query(name, params)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown query name")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid params: {e}")

    repo = get_repo()
    try:
        candidates = repo.search(DOCS_COLLECTION, query=query, limit=limit)
        ids = [d.get("document_id") for d in candidates if d.get("document_id")]
        if dry_run:
            return {"matched": len(ids), "document_ids": ids}
        results: List[Dict[str, Any]] = []
        for did in ids:
            results.append(_cascade_delete_document(repo, str(did)))
        return {"matched": len(ids), "results": results}
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/documents/delete")
def delete_documents_by_query(payload: Dict[str, Any]):
    """
    Delete documents by query (cascades over metadata, chunks, embeddings, and file).

    Body payload example:
    {
      "query": {"author": {"$regex": "Alice", "$options": "i"}},
      "limit": 100,
      "dry_run": false
    }
    """
    query = payload.get("query") or {}
    limit = payload.get("limit")
    dry_run = bool(payload.get("dry_run", False))
    if not isinstance(query, dict):
        raise HTTPException(status_code=400, detail="query must be an object")

    repo = get_repo()
    try:
        candidates = repo.search(DOCS_COLLECTION, query=query, limit=limit)
        ids = [d.get("document_id") for d in candidates if d.get("document_id")]
        if dry_run:
            return {"matched": len(ids), "document_ids": ids}
        results: List[Dict[str, Any]] = []
        for did in ids:
            results.append(_cascade_delete_document(repo, str(did)))
        return {"matched": len(ids), "results": results}
    except (RepoOperationError, DBConnectionError) as e:
        raise HTTPException(status_code=500, detail=str(e))
