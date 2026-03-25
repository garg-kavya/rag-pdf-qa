"""
Embedding Cache
================

Purpose:
    A specialised cache layer that sits in front of EmbeddingService.embed_query().
    Caches the 1536-dimensional query embedding vectors so that identical or
    previously-seen queries do not trigger a redundant OpenAI Embeddings API call.

    This is the highest-ROI cache in the system:
    - embed_query() costs ~100-150ms per call
    - Repeated questions within a session (e.g., user rephrases) hit the cache
    - Common questions across sessions (e.g., "summarise the document") hit the cache

Cache Key Construction:
    key = sha256(query_text.strip().lower())

    Normalisation (strip + lowercase) ensures "What is revenue?" and
    "what is revenue? " map to the same cache entry.

    SHA-256 is used (not the raw string) to keep keys at a fixed length
    and to avoid issues with special characters in cache backends.

TTL:
    Default: 24 hours. Query embeddings are stable — the same text always
    produces the same vector for a given model version. TTL exists only
    to prevent unbounded growth, not for freshness.

Cache Miss Path:
    On miss, EmbeddingCache calls EmbeddingService.embed_query() directly,
    stores the result, and returns it. The caller sees no difference.

Methods:

    get_or_embed(query_text: str) -> list[float]:
        Check cache; on miss, call EmbeddingService and store result.
        Inputs:  query_text — the raw (or reformulated) query string
        Outputs: 1536-dimensional embedding vector

    invalidate(query_text: str) -> None:
        Remove a specific query's embedding from the cache.
        Used in tests and when the embedding model version changes.

    warm(queries: list[str]) -> None:
        Pre-populate the cache with a list of queries.
        Used by scripts/seed_test_data.py to warm common queries.

Dependencies:
    - hashlib (sha256)
    - app.cache.cache_backend (CacheBackend)
    - app.services.embedder (EmbeddingService)
    - app.config (Settings)
"""
