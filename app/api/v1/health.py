"""Health check endpoint."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.document_registry import DocumentRegistry
from app.db.session_store import SessionStore
from app.db.vector_store import VectorStore
from app.dependencies import get_document_registry, get_session_store, get_settings, get_vector_store

router = APIRouter(tags=["health"])
_START_TIME = time.monotonic()


@router.get("/health")
async def health(
    vector_store: VectorStore = Depends(get_vector_store),
    registry: DocumentRegistry = Depends(get_document_registry),
    session_store: SessionStore = Depends(get_session_store),
    settings=Depends(get_settings),
):
    checks: dict[str, str] = {}

    # Vector store check
    try:
        stats = await vector_store.get_collection_stats()
        checks["vector_store"] = "ok"
    except Exception:
        stats = {"total_vectors": 0, "total_documents": 0}
        checks["vector_store"] = "error"

    # Upload dir check
    import os
    checks["upload_dir"] = "ok" if os.path.isdir(settings.upload_dir) else "error"

    all_docs = await registry.get_all()

    status = "healthy" if all(v == "ok" for v in checks.values()) else "unhealthy"
    http_status = 200 if status == "healthy" else 503

    return JSONResponse(
        status_code=http_status,
        content={
            "status": status,
            "version": settings.app_version,
            "checks": checks,
            "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
            "total_documents": len(all_docs),
            "total_vectors": stats.get("total_vectors", 0),
        },
    )
