"""
FastAPI Dependency Injection
=============================

Purpose:
    Provides FastAPI dependency functions that inject shared service instances
    into route handlers. This module is the composition root — it is the only
    place in the application that knows how to wire together services, stores,
    caches, and configuration into the full object graph.

    All instances are created once at application startup (stored on app.state)
    and reused across requests. Dependency functions read from app.state via
    the FastAPI Request object.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pipeline-Level Dependencies  (injected into API handlers)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    get_rag_pipeline() -> RAGPipeline:
        Returns the fully-assembled query orchestrator.
        Wires together: SessionStore, ResponseCache, EmbeddingCache,
        QueryReformulator, RetrieverService, RerankerService,
        MemoryManager, RAGChain, StreamingHandler.
        Injected into POST /query and POST /query/stream handlers.

    get_ingestion_pipeline() -> IngestionPipeline:
        Returns the fully-assembled document ingestion orchestrator.
        Wires together: PDFProcessorService, TextCleanerService,
        ChunkerService, EmbedderService, VectorStore, DocumentRegistry,
        SessionStore.
        Injected into POST /documents/upload handler.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Store-Level Dependencies  (injected where direct store access is needed)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    get_session_store() -> SessionStore:
        Returns the in-memory session store.
        Injected into /sessions endpoints (CRUD operations that don't
        need the full pipeline).

    get_document_registry() -> DocumentRegistry:
        Returns the in-memory document registry.
        Injected into GET /documents and DELETE /documents/{id} handlers
        (status checks and deletions don't need the pipeline).

    get_vector_store() -> VectorStore:
        Returns the configured vector store (FAISS or ChromaDB).
        Injected into DELETE /documents/{id} to remove chunk vectors.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Config-Level Dependencies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    get_settings() -> Settings:
        Returns the validated application settings singleton.
        Injected into the health check endpoint and any handler that
        needs configuration values directly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Service-Level Dependencies  (not injected directly into handlers —
    used internally by pipeline constructors during startup)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    The following are constructed during startup and passed into the
    pipeline constructors. They are not exposed as FastAPI Depends()
    functions because route handlers should never call services directly
    — they go through the pipeline.

    EmbedderService          → used by IngestionPipeline + EmbeddingCache
    EmbeddingCache           → used by RAGPipeline
    ResponseCache            → used by RAGPipeline
    RetrieverService         → used by RAGPipeline
    RerankerService          → used by RAGPipeline
    QueryReformulator        → used by RAGPipeline
    MemoryManager            → used by RAGPipeline (wraps SessionStore)
    RAGChain                 → used by RAGPipeline
    PDFProcessorService      → used by IngestionPipeline
    TextCleanerService       → used by IngestionPipeline
    ChunkerService           → used by IngestionPipeline
    StreamingHandler         → used by RAGPipeline

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Startup Wiring Order
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    1. Settings (no deps)
    2. VectorStore (needs Settings)
    3. SessionStore (needs Settings)
    4. DocumentRegistry (no deps)
    5. InMemoryCache (needs Settings)  ← shared backend
    6. EmbedderService (needs Settings)
    7. EmbeddingCache (needs InMemoryCache + EmbedderService)
    8. ResponseCache (needs InMemoryCache)
    9. RetrieverService (needs VectorStore + Settings)
   10. RerankerService (needs Settings)
   11. QueryReformulator (needs Settings)
   12. MemoryManager (needs SessionStore + ContextBuilder + MemoryCompressor)
   13. RAGChain (needs Settings)
   14. StreamingHandler (no deps)
   15. RAGPipeline (needs 3, 7, 8, 9, 10, 11, 12, 13, 14)
   16. PDFProcessorService (needs Settings)
   17. TextCleanerService (no deps)
   18. ChunkerService (needs Settings)
   19. IngestionPipeline (needs 2, 3, 4, 6, 16, 17, 18)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Dependencies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    fastapi (Depends, Request)
    app.config (Settings, get_settings)
    app.pipeline.rag_pipeline (RAGPipeline)
    app.pipeline.ingestion_pipeline (IngestionPipeline)
    app.db.session_store (SessionStore)
    app.db.document_registry (DocumentRegistry)
    app.db.vector_store (VectorStore)
    app.cache.in_memory_cache (InMemoryCache)
    app.cache.embedding_cache (EmbeddingCache)
    app.cache.response_cache (ResponseCache)
    app.services.embedder (EmbedderService)
    app.services.retriever (RetrieverService)
    app.services.reranker (RerankerService)
    app.services.query_reformulator (QueryReformulator)
    app.services.generator (GeneratorService)
    app.services.pdf_processor (PDFProcessorService)
    app.services.text_cleaner (TextCleanerService)
    app.services.chunker (ChunkerService)
    app.services.streaming (StreamingHandler)
    app.memory.memory_manager (MemoryManager)
    app.memory.context_builder (ContextBuilder)
    app.memory.memory_compressor (MemoryCompressor)
    app.chains.rag_chain (RAGChain)
"""
