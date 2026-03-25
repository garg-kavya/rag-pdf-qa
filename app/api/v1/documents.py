"""
Document Management Endpoints
===============================

Purpose:
    Handles PDF document upload, status checking, listing, and deletion.
    Handlers here are intentionally thin — all ingestion logic is delegated
    to IngestionPipeline; all status reads go via DocumentRegistry.

    Calling convention:
        POST /upload       → validate → save → IngestionPipeline.run() (background)
        GET  /{id}         → DocumentRegistry.get()
        GET  /             → DocumentRegistry.get_all()
        DELETE /{id}       → VectorStore.delete_document() + DocumentRegistry.delete()

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Endpoints
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    POST /api/v1/documents/upload
        Upload a PDF document and trigger async ingestion.

        Request:
            Content-Type: multipart/form-data
            Body:
                file: UploadFile — the PDF binary
                session_id: str (optional) — associate with an existing session

        Handler Steps:
            1. Validate MIME type (must be application/pdf)
            2. Validate file size (≤ MAX_UPLOAD_SIZE_MB)
            3. Save to uploads/ via FileUtils.save_upload()
               → generates document_id (UUID) + unique filename
            4. Register in DocumentRegistry with status="uploaded"
            5. Launch IngestionPipeline.run() as a BackgroundTask
               (returns immediately; processing continues async)
            6. Return 202 Accepted

        Response: 202 Accepted
            DocumentUploadResponse (document_id, status="processing", ...)

        Errors:
            400 — InvalidFileTypeError (not a PDF)
            400 — FileTooLargeError (exceeds limit)
            400 — Empty file

    GET /api/v1/documents/{document_id}
        Retrieve document status and metadata.

        Handler Steps:
            1. DocumentRegistry.get(document_id)
            2. Map Document → DocumentStatusResponse

        Response: 200 OK
            DocumentStatusResponse (includes pdf_metadata and ingestion_metadata
            when status=="ready")

        Errors:
            404 — DocumentNotFoundError

    GET /api/v1/documents
        List all registered documents.

        Query Parameters:
            status: str (optional) — filter by "uploaded"|"processing"|"ready"|"error"
            limit: int = 50
            offset: int = 0

        Response: 200 OK
            DocumentListResponse

    DELETE /api/v1/documents/{document_id}
        Remove a document and all its indexed chunks.

        Handler Steps:
            1. DocumentRegistry.get(document_id) — 404 if not found
            2. VectorStore.delete_document(document_id)
               → removes all chunk vectors and metadata for this document
            3. DocumentRegistry.delete(document_id)
            4. ResponseCache.invalidate_by_document(document_id)
               → evicts any cached responses that referenced this document
            5. Return 200 OK

        Response: 200 OK
            DocumentDeleteResponse (chunks_removed count)

        Errors:
            404 — DocumentNotFoundError

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Dependencies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    fastapi (APIRouter, UploadFile, File, BackgroundTasks, Depends, HTTPException)
    app.schemas.document (DocumentUploadResponse, DocumentStatusResponse,
                          DocumentListResponse, DocumentDeleteResponse)
    app.dependencies (get_ingestion_pipeline, get_document_registry,
                      get_vector_store, get_response_cache)
    app.pipeline.ingestion_pipeline (IngestionPipeline)
    app.db.document_registry (DocumentRegistry)
    app.db.vector_store (VectorStore)
    app.cache.response_cache (ResponseCache)
    app.utils.file_utils (FileUtils.save_upload, FileUtils.validate_pdf)
    app.exceptions (InvalidFileTypeError, FileTooLargeError, DocumentNotFoundError)
"""
