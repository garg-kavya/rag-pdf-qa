"""
Centralized Exception Hierarchy
=================================

Purpose:
    Defines all custom exceptions raised anywhere in the application.
    Centralising them in one module ensures:

    - `error_handler.py` has a single import to resolve every error type
      to an HTTP status code and user-facing message.
    - Service code raises semantically meaningful exceptions instead of
      generic `ValueError` / `RuntimeError`.
    - Test code can assert on specific exception types.

Hierarchy:

    AppError (base)
    │
    ├── IngestionError (errors during the PDF → vector-store pipeline)
    │   ├── PDFParsingError         File corrupted, encrypted, or image-only
    │   ├── TextExtractionError     Parsed PDF yields no usable text
    │   └── ChunkingError           Unexpected failure during text splitting
    │
    ├── EmbeddingError (errors calling the OpenAI Embeddings API)
    │   ├── EmbeddingAPIError       Non-retryable API failure (auth, invalid input)
    │   └── EmbeddingTimeoutError   API did not respond within the deadline
    │
    ├── VectorStoreError (errors in FAISS / ChromaDB operations)
    │   ├── IndexNotFoundError      Vector store has not been initialised
    │   ├── StorageWriteError       Failed to persist vectors or metadata
    │   └── StorageReadError        Failed to search or retrieve vectors
    │
    ├── RetrievalError (errors during the retrieval pipeline)
    │   ├── NoDocumentsError        Session has no documents to search
    │   └── RerankerError           Cross-encoder / MMR reranking failed
    │
    ├── GenerationError (errors during LLM answer generation)
    │   ├── GenerationAPIError      Non-retryable OpenAI Chat API failure
    │   ├── GenerationTimeoutError  LLM did not respond within the deadline
    │   ├── ContextTooLongError     Retrieved chunks exceed model context window
    │   └── CitationExtractionError Could not parse [Source N] refs from response
    │
    ├── SessionError (session lifecycle errors)
    │   ├── SessionNotFoundError    session_id does not exist in the store
    │   ├── SessionExpiredError     session_id existed but TTL has elapsed
    │   └── SessionCapacityError    MAX_CONVERSATION_TURNS exceeded (should auto-trim)
    │
    ├── DocumentError (document registry errors)
    │   ├── DocumentNotFoundError   document_id does not exist
    │   └── DocumentNotReadyError   document is still processing (status != "ready")
    │
    ├── CacheError (caching layer errors — non-fatal by design)
    │   ├── CacheReadError          Failed to read from cache backend
    │   └── CacheWriteError         Failed to write to cache backend
    │
    └── ValidationError (request-level validation beyond Pydantic)
        ├── FileTooLargeError       Uploaded file exceeds MAX_UPLOAD_SIZE_MB
        ├── InvalidFileTypeError    Uploaded file is not a PDF
        └── InvalidQueryError       Question is empty or exceeds length limit

Attributes on AppError (inherited by all subclasses):
    message: str
        Human-readable description, safe to return to clients.
    detail: str | None
        Technical context for internal logging (never sent to clients in production).
    request_id: str | None
        Trace ID set by the error handler middleware after the exception is caught.

HTTP Status Code Mapping (used by error_handler.py):
    PDFParsingError / TextExtractionError   -> 422 Unprocessable Entity
    EmbeddingAPIError / GenerationAPIError  -> 502 Bad Gateway
    EmbeddingTimeoutError / Timeout*        -> 504 Gateway Timeout
    VectorStoreError / StorageWriteError    -> 500 Internal Server Error
    SessionNotFoundError / DocumentNotFound -> 404 Not Found
    SessionExpiredError                     -> 410 Gone
    NoDocumentsError                        -> 409 Conflict
    FileTooLargeError / InvalidFileType*    -> 400 Bad Request
    CacheError                              -> logged only; request continues
    ValidationError (subclasses)            -> 400 Bad Request

Design Notes:
    - CacheError subclasses are non-fatal: the caching layer catches them
      internally and falls through to the uncached code path. They are
      logged as WARNING, not re-raised.
    - All AppError subclasses accept keyword-only `detail` to avoid
      accidentally exposing it to callers who only check `message`.

Dependencies:
    - None (stdlib only — no circular imports)
"""
