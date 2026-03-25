"""
Cache Layer Tests
==================

Purpose:
    Tests for the caching infrastructure: InMemoryCache, EmbeddingCache,
    and ResponseCache.

InMemoryCache Tests:

    test_set_and_get:
        Store a value; retrieve it; assert equality.

    test_get_missing_key_returns_none:
        Querying a non-existent key returns None (no exception).

    test_ttl_expiry:
        Set a value with ttl_seconds=1; sleep 2s; assert get() returns None.

    test_lru_eviction:
        Fill cache to max_size; add one more entry; assert the LRU entry
        has been evicted.

    test_delete_removes_key:
        Set, delete, then assert get() returns None.

    test_stats_counts_hits_and_misses:
        After a mix of hits and misses, stats() returns correct counters.

    test_clear_empties_cache:
        After clear(), all keys return None.

EmbeddingCache Tests:

    test_get_or_embed_calls_embedder_on_miss:
        First call for a new query invokes EmbeddingService.embed_query().

    test_get_or_embed_returns_cached_on_hit:
        Second call for the same query does NOT invoke EmbeddingService.

    test_key_normalisation:
        "What is X?" and " what is x? " map to the same cache entry.

    test_invalidate_removes_embedding:
        After invalidate(), the next get_or_embed() calls the embedder again.

ResponseCache Tests:

    test_get_or_generate_calls_fn_on_miss:
        First query invokes the generate_fn callable.

    test_get_or_generate_returns_cached_on_hit:
        Second identical query does NOT call generate_fn; returns cached answer.

    test_cache_hit_flag_is_set:
        Cached responses have cache_hit=True; fresh responses have cache_hit=False.

    test_turn_count_change_invalidates_cache:
        Changing turn_count in the key causes a cache miss (history changed).

    test_invalidate_session_removes_all_entries:
        After invalidate_session(), all response cache entries for that session
        return misses.

    test_streaming_queries_bypass_cache:
        Ensure ResponseCache is not consulted for stream=True queries.

Dependencies:
    - pytest
    - pytest-asyncio
    - app.cache.in_memory_cache
    - app.cache.embedding_cache
    - app.cache.response_cache
    - unittest.mock (for EmbeddingService mock)
"""
