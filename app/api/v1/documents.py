"""Document management endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile

from app.cache.response_cache import ResponseCache
from app.db.document_registry import DocumentRegistry
from app.db.vector_store import VectorStore
from app.dependencies import (
    get_current_user,
    get_document_registry,
    get_ingestion_pipeline,
    get_response_cache,
    get_settings,
    get_vector_store,
)
from app.models.user import User
from app.exceptions import DocumentNotFoundError, InvalidFileTypeError
from app.pipeline.ingestion_pipeline import IngestionPipeline
from app.schemas.document import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from app.utils.file_utils import save_upload

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentUploadResponse, status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_id: str | None = Form(None),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    registry: DocumentRegistry = Depends(get_document_registry),
    settings=Depends(get_settings),
    current_user: User = Depends(get_current_user),
):
    if not file.content_type or "pdf" not in file.content_type.lower():
        # Allow even if content_type isn't set — validate_pdf via magic bytes
        pass

    file_path, document_id = await save_upload(
        file, settings.upload_dir, settings.max_upload_size_mb
    )

    doc = await registry.register(
        document_id=document_id,
        filename=file.filename or "upload.pdf",
        file_path=file_path,
        file_size_bytes=0,
    )

    background_tasks.add_task(
        pipeline.run,
        file_path=file_path,
        document_id=document_id,
        filename=file.filename or "upload.pdf",
        session_id=session_id,
    )

    return DocumentUploadResponse(
        document_id=document_id,
        filename=file.filename or "upload.pdf",
        file_size_bytes=0,
        status="processing",
        message="Document received and is being processed.",
        created_at=doc.created_at,
    )


@router.get("/{document_id}", response_model=DocumentStatusResponse)
async def get_document(
    document_id: str,
    registry: DocumentRegistry = Depends(get_document_registry),
    current_user: User = Depends(get_current_user),
):
    doc = await registry.get(document_id)
    if doc is None:
        raise DocumentNotFoundError(f"Document {document_id} not found.")
    return _doc_to_response(doc)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    status: str | None = None,
    registry: DocumentRegistry = Depends(get_document_registry),
    current_user: User = Depends(get_current_user),
):
    docs = await registry.get_all(status=status)
    return DocumentListResponse(
        documents=[_doc_to_response(d) for d in docs],
        total_count=len(docs),
    )


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: str,
    registry: DocumentRegistry = Depends(get_document_registry),
    vector_store: VectorStore = Depends(get_vector_store),
    response_cache: ResponseCache = Depends(get_response_cache),
    current_user: User = Depends(get_current_user),
):
    doc = await registry.get(document_id)
    if doc is None:
        raise DocumentNotFoundError(f"Document {document_id} not found.")

    chunks_removed = await vector_store.delete_document(document_id)
    await registry.delete(document_id)
    await response_cache.invalidate_by_document(document_id)

    return DocumentDeleteResponse(
        document_id=document_id,
        message="Document deleted.",
        chunks_removed=chunks_removed,
    )


def _doc_to_response(doc) -> DocumentStatusResponse:
    return DocumentStatusResponse(
        document_id=doc.document_id,
        filename=doc.filename,
        status=doc.status,
        page_count=doc.page_count,
        total_chunks=doc.total_chunks,
        pdf_metadata=doc.pdf_metadata.model_dump() if doc.pdf_metadata else None,
        ingestion_metadata=doc.ingestion_metadata.model_dump() if doc.ingestion_metadata else None,
        created_at=doc.created_at,
        processed_at=doc.processed_at,
        error_message=doc.error_message,
    )
