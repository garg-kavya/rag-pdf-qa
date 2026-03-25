"""
Response Cache
===============

Purpose:
    Caches complete GeneratedAnswer objects for semantically identical queries
    within the same session context. Prevents redundant LLM generation calls
    when a user submits the same question twice in quick succession.

    Inserted at Step 2 of RAGPipeline.run() (non-streaming only):
        RAGPipeline.run()
            ├── Step 2: ResponseCache.get_or_generate(...)
            │       HIT  → return immediately (skip steps 3-11)
            │       MISS → execute steps 3-11 as generate_fn, then store result
            └── ...

When to Cache vs. Not:
    Cached:
        - Same (normalised) question + same session + same documents + same turn count
    Not cached:
        - Streaming queries — SSE token streams cannot be replayed from a cache object
        - Any query where turn_count has advanced (prior answer changed context)

Cache Key Construction:
    key = sha256(
        session_id
        + "|" + query_text.strip().lower()
        + "|" + ",".join(sorted(document_ids))
        + "|" + str(turn_count)
    )

    turn_count is included so that a cached response from turn 2 is never
    served at turn 4, where conversation context has changed.

TTL:
    Default: 60 seconds (RESPONSE_CACHE_TTL_SECONDS in CacheSettings).
    Short because the main use-case is double-submission prevention.

Cache Hit Behaviour:
    On hit, the cached GeneratedAnswer is returned with:
        cache_hit = True
        pipeline_metadata.response_cache_hit = True
    All other fields are identical to the originally generated answer.

Methods:

    get_or_generate(
        query_text: str,
        session_id: str,
        document_ids: list[str],
        turn_count: int,
        generate_fn: Callable[[], Awaitable[GeneratedAnswer]]
    ) -> GeneratedAnswer:
        Checks the cache; on miss calls generate_fn(), stores and returns result.
        generate_fn is the zero-argument async callable that runs steps 3-11
        of RAGPipeline. The cache wraps the entire downstream pipeline.
        Inputs:
            query_text   — standalone (reformulated) query
            session_id   — active session UUID
            document_ids — documents scoped to this query
            turn_count   — current session turn count (for key invalidation)
            generate_fn  — async callable returning GeneratedAnswer
        Outputs:
            GeneratedAnswer with cache_hit flag set

    invalidate_session(session_id: str) -> None:
        Remove all cached responses for a session.
        Called by DELETE /api/v1/sessions/{session_id}.

    invalidate_by_document(document_id: str) -> None:
        Remove all cached responses that were generated using a specific
        document. Called by DELETE /api/v1/documents/{document_id} to
        prevent stale answers being served after a document is removed.
        Implementation: scan cache keys containing the document_id string.
        This is O(n) over cache size — acceptable given typical cache sizes
        (<1000 entries) and the infrequency of document deletions.

    get_stats() -> dict:
        Returns cache hit/miss counters and current size.
        Exposed via GET /api/v1/health.

Dependencies:
    - hashlib (sha256)
    - app.cache.cache_backend (CacheBackend)
    - app.models.query (GeneratedAnswer)
    - app.exceptions (CacheReadError, CacheWriteError)
    - app.config (CacheSettings)
"""
