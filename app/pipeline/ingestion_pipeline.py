"""
Ingestion Pipeline — PDF Processing Orchestrator
=================================================

Purpose:
    Orchestrates the complete PDF ingestion workflow from raw uploaded file
    to indexed vectors. Called by the documents API handler after file upload
    validation. Runs asynchronously in a background task so the API returns
    202 Accepted immediately while processing continues.

    Like RAGPipeline for queries, this is the single authoritative place
    that knows the ingestion stage order and error recovery strategy.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Full Execution Flow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  0. PRE-CONDITIONS (enforced by calling API handler, not here)
     ├── File is a valid PDF (MIME check, magic bytes)
     ├── File size ≤ MAX_UPLOAD_SIZE_MB
     └── file_path exists on disk and document_id is registered with status="uploaded"

  1. STATUS UPDATE → "processing"
     └── DocumentRegistry.update_status(document_id, "processing")

  2. PDF PARSING
     ├── PDFProcessorService.parse(file_path, document_id)
     │       → tries PyMuPDF first
     │       → falls back to pdfplumber if chars_per_page < threshold
     ├── Returns: ParsedDocument (pages, pdf_metadata, parser_used)
     ├── On PDFParsingError:
     │       → update status = "error"
     │       → re-raise (API error handler formats response)
     └── Attaches PDFMetadata to document record

  3. TEXT CLEANING
     ├── TextCleanerService.clean(parsed_document)
     │       → Unicode normalisation, whitespace, headers/footers, etc.
     └── Returns: cleaned_text, page_boundary_offsets

  4. CHUNKING
     ├── ChunkerService.chunk(
     │       cleaned_text, page_boundary_offsets,
     │       document_id, document_name)
     │       → Recursive character split at 512 tokens / 64 overlap
     └── Returns: list[Chunk] with metadata populated

  5. BATCH EMBEDDING
     ├── EmbedderService.embed_chunks(chunks)
     │       → Batched OpenAI Embeddings API calls (100 chunks/batch)
     │       → Populates chunk.embedding on each Chunk
     ├── On EmbeddingAPIError / EmbeddingTimeoutError:
     │       → update status = "error"
     │       → re-raise
     └── Returns: list[Chunk] with embeddings

  6. VECTOR STORAGE
     ├── VectorStore.add_chunks(chunks)
     │       → Stores vectors + ChunkMetadata for each chunk
     ├── On StorageWriteError:
     │       → update status = "error"
     │       → re-raise
     └── Returns: count of vectors stored

  7. STATUS UPDATE → "ready" + INGESTION METADATA
     ├── DocumentRegistry.update_status(document_id, "ready")
     └── DocumentRegistry.set_ingestion_metadata(document_id,
               IngestionMetadata(
                   document_id, filename, page_count,
                   total_chunks=len(chunks),
                   total_tokens=sum(c.token_count for c in chunks),
                   parser_used, ingestion_time_ms, embedding_model))

  8. SESSION ASSOCIATION (if session_id was provided)
     └── SessionStore.add_document_to_session(session_id, document_id)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Methods
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    run(
        file_path: str,
        document_id: str,
        filename: str,
        session_id: str | None = None
    ) -> IngestionMetadata:
        Runs the full ingestion pipeline synchronously.
        Intended to be called inside asyncio.to_thread() or a
        BackgroundTask so it doesn't block the event loop.
        Inputs:
            file_path   — absolute path to the saved PDF on disk
            document_id — pre-assigned UUID for this document
            filename    — original uploaded filename (for metadata)
            session_id  — if provided, associates doc with this session
        Outputs:
            IngestionMetadata (summary of what was processed)
        Raises:
            PDFParsingError     — PDF could not be parsed
            EmbeddingAPIError   — embedding call failed
            StorageWriteError   — vector store write failed

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Dependencies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    app.services.pdf_processor   (PDFProcessorService)
    app.services.text_cleaner    (TextCleanerService)
    app.services.chunker         (ChunkerService)
    app.services.embedder        (EmbedderService)
    app.db.vector_store          (VectorStore)
    app.db.session_store         (SessionStore — optional association)
    app.db.document_registry     (DocumentRegistry — status tracking)
    app.schemas.metadata         (IngestionMetadata, PDFMetadata, ChunkMetadata)
    app.exceptions               (PDFParsingError, EmbeddingAPIError, StorageWriteError)
    app.config                   (Settings)
"""
