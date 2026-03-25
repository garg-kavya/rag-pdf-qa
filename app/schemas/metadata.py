"""
Metadata Schemas
=================

Purpose:
    Typed Pydantic models for every metadata structure used in the system.
    Consolidates metadata definitions that were previously scattered across
    docstrings in chunk.py, vector_store.py, faiss_store.py, and chroma_store.py.

    These schemas serve three roles:
    1. Runtime validation — Pydantic enforces field types when metadata is
       constructed during ingestion and serialised into the vector DB.
    2. Documentation — a single authoritative reference for what fields
       exist on each metadata object.
    3. Deserialisation — when metadata is read back from FAISS or ChromaDB
       (which returns plain dicts), these models parse and validate it.

Schemas:

    PDFMetadata
        Metadata extracted from the PDF file itself during parsing.
        Stored on the Document domain model.

        Fields:
            title: str | None
                PDF Info dict "Title" field. None if absent.
            author: str | None
                PDF Info dict "Author" field.
            creation_date: str | None
                PDF creation date as ISO 8601 string or raw PDF date string.
            producer: str | None
                Software that produced the PDF (e.g., "Microsoft Word").
            page_count: int
                Total number of pages in the document.
            file_size_bytes: int
                Size of the uploaded file in bytes.
            parser_used: str
                Which parser produced the text: "pymupdf" or "pdfplumber".

    ChunkMetadata
        Metadata stored alongside each vector in the vector database.
        This is the canonical shape of the metadata dict that FAISS stores
        in its parallel dict and ChromaDB stores in its metadata field.

        Fields:
            chunk_id: str
                UUID4 uniquely identifying this chunk.
            document_id: str
                UUID4 of the parent document. Used for document-scoped filtering.
            document_name: str
                Original PDF filename. Denormalised for fast citation construction
                without a separate document lookup.
            chunk_index: int
                Zero-based sequential position of this chunk within the document.
            page_numbers: list[int]
                Pages this chunk spans. Serialised as JSON string in ChromaDB
                (ChromaDB metadata values must be scalar); parsed back on read.
            token_count: int
                Number of cl100k_base tokens in this chunk.
            text: str
                The full chunk text. Stored in metadata so retrieval returns
                complete chunks without a separate fetch step.

        Constraints:
            - chunk_index >= 0
            - page_numbers must be non-empty
            - token_count must be > 0 and <= CHUNK_SIZE_TOKENS

    RetrievalMetadata
        Diagnostic metadata attached to a RetrievedContext result.
        Returned to callers in the API response retrieval_metadata field.

        Fields:
            retrieval_time_ms: float
                Wall-clock time from search() call to ranked results returned.
            candidates_considered: int
                Number of vectors fetched before threshold filtering (top_k * 2).
            candidates_after_threshold: int
                Number of candidates remaining after similarity threshold filter.
            chunks_used: int
                Final number of chunks returned after MMR (= top_k or fewer).
            mmr_applied: bool
                Whether MMR re-ranking was executed (False if < 2 candidates).
            reranker_applied: bool
                Whether the cross-encoder reranker was applied.
            similarity_scores: list[float]
                Cosine similarity scores of the final returned chunks, in rank order.
            top_k_requested: int
                The top_k value used for this retrieval (may differ from default).
            similarity_threshold_used: float
                The threshold applied (may be session-overridden).

    SessionMetadata
        Lightweight metadata about a session, safe to expose in list/summary APIs.
        Does NOT include full conversation history (use SessionDetailResponse for that).

        Fields:
            session_id: str
                UUID4 session identifier.
            document_count: int
                Number of documents associated with this session.
            turn_count: int
                Number of completed Q&A turns.
            created_at: datetime
                When the session was created.
            last_active_at: datetime
                When the session last processed a query.
            expires_at: datetime
                When the session will be auto-deleted (last_active_at + TTL).
            is_expired: bool
                Computed field: True if now() > expires_at.

    IngestionMetadata
        Summary metadata produced at the end of the ingestion pipeline,
        returned as part of DocumentUploadResponse.

        Fields:
            document_id: str
            filename: str
            page_count: int
            total_chunks: int
            total_tokens: int
                Sum of token_count across all chunks.
            parser_used: str
                "pymupdf" or "pdfplumber".
            ingestion_time_ms: float
                Wall-clock time for the full parse → embed → store pipeline.
            embedding_model: str
                The embedding model used (e.g., "text-embedding-3-small").

Dependencies:
    - pydantic (BaseModel, Field, computed_field, model_validator)
    - datetime
    - json (for page_numbers serialisation / deserialisation)
"""
