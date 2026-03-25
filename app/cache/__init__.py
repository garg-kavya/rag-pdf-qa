"""
Caching Package
================

Purpose:
    Provides a multi-level caching layer to reduce redundant OpenAI API calls
    and repeated vector searches. All cache misses are transparent — upstream
    code falls through to the uncached path without changes.

Modules:

    cache_backend
        Abstract interface that all cache implementations must satisfy.
        Defines get / set / delete / exists / clear operations.

    in_memory_cache
        LRU in-memory implementation backed by functools.lru_cache or
        collections.OrderedDict. Zero-latency access, not persistent across
        restarts. Default for development.

    embedding_cache
        Specialised cache for query embeddings. Keys queries by their exact
        text (after normalisation). Avoids a ~100-150ms OpenAI API call for
        repeated or near-duplicate queries.

    response_cache
        Caches complete GeneratedAnswer objects for identical (query, session)
        pairs. Short TTL (60 seconds) — prevents redundant generation when a
        user asks the same question twice in quick succession.

Cache Key Design:
    Embedding cache key: sha256(query_text.strip().lower())
    Response cache key:  sha256(session_id + "|" + query_text.strip().lower()
                                + "|" + sorted(document_ids).join(","))

Error Handling:
    All cache operations wrap their internals in try/except CacheError.
    A cache failure never propagates — the caller receives None (cache miss)
    and continues on the uncached path. This is intentional: caching is a
    performance optimisation, not a correctness requirement.
"""
