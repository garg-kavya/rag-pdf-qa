"""
Document Registry
==================

Purpose:
    Manages the in-process registry of all uploaded documents, tracking
    their processing status, PDF metadata, and ingestion results.

    This module fills a gap that was previously undeclared: the API handlers
    and ingestion pipeline needed somewhere to read/write document status
    and metadata without coupling to the vector store. The vector store
    owns chunk vectors; the DocumentRegistry owns document-level state.

Relationship to Vector Store:
    ┌──────────────────────┐        ┌──────────────────────────┐
    │  DocumentRegistry    │        │  VectorStore             │
    │  (document-level)    │        │  (chunk-level)           │
    │                      │        │                          │
    │  document_id → {     │        │  chunk vectors +         │
    │    filename,         │        │  ChunkMetadata           │
    │    status,           │        │  (keyed by document_id   │
    │    page_count,       │        │   for scoped retrieval)  │
    │    pdf_metadata,     │        │                          │
    │    ingestion_meta    │        │                          │
    │  }                   │        │                          │
    └──────────────────────┘        └──────────────────────────┘

Storage Model:
    dict[str, Document] — document_id → Document domain object.

    In-memory by design: document metadata is small (~1KB per document),
    access is frequent (every query validates document_ids), and
    persistence is optional (reconstructable from vector store on restart).

Methods:

    register(
        document_id: str,
        filename: str,
        file_path: str,
        file_size_bytes: int
    ) -> Document:
        Creates a new Document record with status="uploaded".
        Called by the documents API handler immediately after file save.
        Inputs: upload file metadata
        Outputs: Document domain object

    update_status(
        document_id: str,
        status: str,
        error_message: str | None = None
    ) -> None:
        Updates the processing status of a document.
        Valid transitions:
            "uploaded" → "processing"
            "processing" → "ready"
            "processing" → "error"
        Sets processed_at timestamp when transitioning to "ready" or "error".

    set_ingestion_metadata(
        document_id: str,
        pdf_metadata: PDFMetadata,
        ingestion_metadata: IngestionMetadata
    ) -> None:
        Attaches the parsed PDF metadata and ingestion summary to the
        document record. Called by IngestionPipeline on successful completion.

    get(document_id: str) -> Document | None:
        Retrieve a document by ID. Returns None if not found.

    get_all(status: str | None = None) -> list[Document]:
        Return all documents, optionally filtered by status.
        Used by GET /api/v1/documents list endpoint.

    delete(document_id: str) -> bool:
        Remove a document record. Returns True if found and deleted.
        Called after VectorStore.delete_document() succeeds.

    exists(document_id: str) -> bool:
        Fast existence check without returning the full object.

Thread Safety:
    Uses asyncio.Lock for concurrent access safety (same pattern as
    SessionStore).

Persistence (optional, future):
    For production deployments that need registry persistence across
    restarts, this can be backed by a SQLite or PostgreSQL table via
    SQLAlchemy. The interface above remains unchanged; only the
    storage implementation changes.

Dependencies:
    - asyncio
    - app.models.document (Document)
    - app.schemas.metadata (PDFMetadata, IngestionMetadata)
    - app.exceptions (DocumentNotFoundError)
"""
