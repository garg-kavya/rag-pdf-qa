"""
In-Memory LRU Cache Backend
=============================

Purpose:
    Implements CacheBackend using an in-process LRU (Least Recently Used)
    dictionary. Zero-latency access, no external dependencies.
    The default cache backend for development and single-instance deployments.

Implementation Notes:

    Storage:
        collections.OrderedDict keyed by cache key string. Each entry stores:
        {
            "value": <serialised value>,
            "expires_at": float (Unix timestamp) | None
        }

    Eviction:
        1. TTL eviction: on every get(), if the entry's expires_at < now(),
           the entry is deleted and None returned (treated as a miss).
        2. LRU eviction: when current_size >= max_size, the least-recently-used
           entry is removed to make room. OrderedDict.move_to_end() tracks
           recency efficiently.

    Concurrency:
        Uses asyncio.Lock to protect all mutations. Safe for concurrent async
        access within a single process.

    Persistence:
        None. Cache is empty on startup and lost on shutdown. This is
        acceptable because all cached data can be recomputed:
        - Embeddings: recomputed via OpenAI API
        - Responses: regenerated via the full pipeline

Configuration (from app.config):
    CACHE_MAX_SIZE: int = 1000
        Maximum number of entries before LRU eviction kicks in.
    CACHE_DEFAULT_TTL_SECONDS: int = 3600
        Default TTL applied when callers pass ttl_seconds=None.
        Can be overridden per-call.

Methods:
    Implements all CacheBackend interface methods.

Dependencies:
    - collections (OrderedDict)
    - asyncio
    - time
    - app.cache.cache_backend (CacheBackend)
    - app.exceptions (CacheReadError, CacheWriteError)
    - app.config (Settings)
"""
