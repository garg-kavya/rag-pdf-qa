"""
RAG Pipeline — Central Query Orchestrator
==========================================

Purpose:
    The single entry point for all query-answer operations. API handlers
    call RAGPipeline.run() or RAGPipeline.run_stream(). No other layer
    (API, chain, service) should orchestrate the full pipeline end-to-end.

    This module owns the authoritative execution order and wires together:
        caches, session/memory, reformulation, embedding, retrieval,
        reranking, history formatting, LLM generation, and turn persistence.

Why a Dedicated Pipeline Layer (not rag_chain.py):
    app/chains/rag_chain.py is responsible for the LangChain/LangGraph
    graph definition and LLM interaction only. It is infrastructure —
    it does not know about caches, the reranker, or memory compression.
    RAGPipeline is business logic — it decides WHAT to call, in WHAT order,
    with WHAT fallbacks.

    Splitting them keeps:
    - chains/ swappable (swap LangGraph for raw OpenAI calls without
      changing the pipeline)
    - pipeline/ testable without any LLM (mock the chain)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Full Execution Flow  (non-streaming)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. VALIDATE SESSION                                         ~0ms
     ├── SessionStore.get_session(session_id)
     ├── Raise SessionNotFoundError / SessionExpiredError
     └── Extract: document_ids, turn_count

  2. RESPONSE CACHE CHECK (non-streaming only)                ~1ms
     ├── ResponseCache.get_or_generate(query, session_id,
     │       document_ids, turn_count, generate_fn=<step 3-9>)
     ├── HIT  → return cached GeneratedAnswer immediately
     └── MISS → continue to step 3

  3. QUERY REFORMULATION (conditional)                     0–400ms
     ├── IF turn_count == 0: standalone_query = raw_query   (0ms)
     └── ELSE: QueryReformulator.reformulate(query, history) (~300ms)

  4. QUERY EMBEDDING (cached)                            ~1–150ms
     ├── EmbeddingCache.get_or_embed(standalone_query)
     ├── HIT  → return cached vector                         (~1ms)
     └── MISS → EmbeddingService.embed_query()             (~150ms)
                  → store in EmbeddingCache

  5. RETRIEVAL                                           ~10–100ms
     ├── RetrieverService.retrieve(
     │       query_embedding, document_ids, top_k=top_k_candidates)
     │   Internally: vector search → score threshold filter
     └── Returns: list[ScoredChunk] (pre-MMR candidates)

  6. RERANKING (conditional)                             ~0–400ms
     ├── IF RerankerService.is_enabled():
     │       RerankerService.rerank(standalone_query, candidates)
     │       → updates ScoredChunk.similarity_score (reranker score)
     │       → preserves ScoredChunk.bi_encoder_score
     └── ELSE: candidates pass through unchanged

  7. MMR DIVERSITY SELECTION                               ~5–20ms
     ├── RetrieverService.apply_mmr(reranked_candidates, top_k)
     │       score = λ·relevance − (1−λ)·max_similarity_to_selected
     └── Returns: final top_k ScoredChunk list

  8. MEMORY READ                                             ~1ms
     └── MemoryManager.get_formatted_history(
               session_id, token_budget=MEMORY_TOKEN_BUDGET)
         → Returns formatted history string for prompt injection

  9. CONTEXT ASSEMBLY → QueryContext populated:
     │   raw_query, standalone_query, query_embedding,
     │   session_id, document_ids, query_id (new UUID),
     │   formatted_history, reranker_applied, cache_hit=False

 10. LLM GENERATION                                   ~500–1500ms
     ├── RAGChain.invoke(query_context, retrieved_context)
     │       → Builds prompt (system + context + history + question)
     │       → Calls OpenAI Chat Completion API
     │       → Extracts and validates citations
     └── Returns: GeneratedAnswer

 11. MEMORY WRITE                                           ~1ms
     └── MemoryManager.record_turn(session_id, ...)
         → Appends ConversationTurn to session
         → Triggers MemoryCompressor if turn_count ≥ threshold

 12. RETURN GeneratedAnswer

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Streaming Variant  (run_stream)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Steps 1, 3–9 are identical to the non-streaming flow (all blocking).
  Step 2 (ResponseCache) is SKIPPED — streaming responses cannot be
  replayed from a cached object.
  Step 10 uses RAGChain.stream() → yields SSE tokens via StreamingHandler.
  Step 11 (memory write) executes after the stream is exhausted.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Error Handling
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  All AppError subclasses raised by any called service propagate up
  to the FastAPI error_handler middleware unchanged. The pipeline does
  not catch and re-wrap them (avoids double-wrapping).

  Exception: CacheError is caught internally (cache misses are silently
  treated as misses; the pipeline continues on the uncached path).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Methods
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    run(
        raw_query: str,
        session_id: str,
        document_ids: list[str] | None = None,
        top_k: int | None = None
    ) -> GeneratedAnswer:
        Full synchronous pipeline. Consults and writes ResponseCache.
        Inputs:
            raw_query    — user's original question text
            session_id   — active session UUID
            document_ids — optional override; defaults to all session docs
            top_k        — optional retrieval override; defaults to settings.TOP_K
        Outputs:
            GeneratedAnswer with answer_text, citations, confidence,
            retrieval_context, query_id, cache_hit, pipeline_metadata

    run_stream(
        raw_query: str,
        session_id: str,
        document_ids: list[str] | None = None,
        top_k: int | None = None
    ) -> AsyncGenerator[StreamingChunk, None]:
        Streaming pipeline. Yields SSE events; bypasses ResponseCache.
        Inputs: same as run()
        Outputs: async generator of StreamingChunk events:
            event="token"    → {"text": str, "query_id": str}
            event="citation" → {"citations": list[Citation], "query_id": str}
            event="done"     → {"query_id": str, "total_tokens": int,
                                "retrieval_time_ms": float}
            event="error"    → {"message": str, "query_id": str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Dependencies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    app.db.session_store          (SessionStore — session validation)
    app.cache.response_cache      (ResponseCache — full answer cache)
    app.cache.embedding_cache     (EmbeddingCache — query vector cache)
    app.services.query_reformulator (QueryReformulator)
    app.services.retriever        (RetrieverService)
    app.services.reranker         (RerankerService)
    app.memory.memory_manager     (MemoryManager — history read/write)
    app.chains.rag_chain          (RAGChain — LLM generation only)
    app.services.streaming        (StreamingHandler — SSE formatting)
    app.models.query              (QueryContext, GeneratedAnswer, StreamingChunk)
    app.schemas.metadata          (RetrievalMetadata, PipelineMetadata)
    app.exceptions                (SessionNotFoundError, NoDocumentsError, ...)
    app.config                    (Settings)
"""
