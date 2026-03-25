"""
Cache Backend Abstract Interface
==================================

Purpose:
    Defines the contract that every cache implementation must satisfy.
    Allows the application to swap backends (in-memory LRU, Redis, Memcached)
    without changing any caching consumer code.

Interface Methods:

    get(key: str) -> Any | None:
        Retrieve a cached value by key.
        Inputs:  key — the cache key string
        Outputs: The cached value, or None on miss or error.
        Guarantees: Never raises (swallows CacheReadError internally).

    set(key: str, value: Any, ttl_seconds: int | None = None) -> None:
        Store a value under a key with an optional expiry.
        Inputs:
            key         — the cache key string
            value       — any JSON-serialisable object
            ttl_seconds — seconds until auto-expiry; None = no expiry
        Guarantees: Never raises (swallows CacheWriteError internally).

    delete(key: str) -> None:
        Remove a key from the cache. No-op if key does not exist.

    exists(key: str) -> bool:
        Check if a key exists without fetching its value.
        Outputs: True if key exists and has not expired.

    clear() -> None:
        Remove all entries from this cache. Used in tests and on shutdown.

    stats() -> dict:
        Return diagnostic counters for monitoring.
        Keys: hits, misses, sets, deletes, errors, current_size
        Used by the health check endpoint and benchmarking scripts.

Serialisation Contract:
    Implementations must handle serialisation/deserialisation of values.
    Recommended: JSON for primitive types and Pydantic models (.model_dump()
    on write, model_validate() on read). Embedding vectors (list[float]) are
    stored as JSON arrays.

Dependencies:
    - abc (ABC, abstractmethod)
    - app.exceptions (CacheReadError, CacheWriteError)
"""
