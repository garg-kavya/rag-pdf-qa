"""
RAG Pipeline Integration Tests
================================

Purpose:
    End-to-end tests for the RAGPipeline orchestrator. Verifies that all
    pipeline stages are called in the correct order and that outputs from
    each stage flow correctly into the next.

    All external services (OpenAI, vector DB) are mocked so these tests
    run without network access.

Test Cases:

    test_run_first_turn_no_reformulation:
        On the first turn of a session (turn_count == 0), assert that
        QueryReformulator is NOT called and standalone_query == raw_query.

    test_run_follow_up_triggers_reformulation:
        On the second turn, assert QueryReformulator.reformulate() is called
        with the correct history.

    test_run_checks_response_cache_before_pipeline:
        Assert ResponseCache.get_or_generate() is called before any
        embedding/retrieval/generation step.

    test_run_returns_cached_answer_on_hit:
        When ResponseCache returns a hit, assert the full pipeline steps
        (embedding, retrieval, generation) are NOT called.

    test_run_embedding_uses_cache:
        Assert EmbeddingCache.get_or_embed() is called (not EmbeddingService
        directly).

    test_run_retrieval_receives_embedding:
        Assert RetrieverService.retrieve() is called with the embedding from
        EmbeddingCache, not a fresh embedding.

    test_run_reranking_called_when_enabled:
        When RerankerService.is_enabled() returns True, assert
        RerankerService.rerank() is called with the retrieve() output.

    test_run_reranking_skipped_when_disabled:
        When RerankerService.is_enabled() returns False, assert
        RerankerService.rerank() is NOT called.

    test_run_mmr_applied_after_reranking:
        Assert RetrieverService.apply_mmr() is called AFTER reranking
        (if enabled) or directly after threshold filtering (if disabled).

    test_run_memory_read_before_generation:
        Assert MemoryManager.get_formatted_history() is called BEFORE
        RAGChain.invoke().

    test_run_chain_receives_formatted_history:
        Assert that the QueryContext passed to RAGChain.invoke() contains
        the formatted_history string from MemoryManager.

    test_run_memory_write_after_generation:
        Assert MemoryManager.record_turn() is called AFTER RAGChain returns.

    test_run_stream_skips_response_cache:
        Assert ResponseCache is NOT consulted in run_stream().

    test_run_stream_yields_token_events:
        Assert run_stream() yields events with event="token" before "done".

    test_run_stream_yields_citation_event:
        Assert a single event with event="citation" is yielded after tokens.

    test_run_stream_memory_write_after_stream_exhausted:
        Assert MemoryManager.record_turn() is called only after the full
        stream is consumed (not at stream start).

    test_run_propagates_session_not_found:
        When SessionStore returns None, assert SessionNotFoundError propagates
        to the caller (not caught internally).

    test_run_propagates_no_documents_error:
        When document_ids is empty, assert NoDocumentsError propagates.

    test_run_reranker_failure_falls_back_to_bi_encoder:
        When RerankerService.rerank() raises RerankerError, assert the pipeline
        falls back to bi-encoder ordering (logs a warning, does not fail).

    test_pipeline_metadata_populated:
        Assert the returned GeneratedAnswer.pipeline_metadata contains
        non-zero timing values for each stage.

    test_cache_hit_flag_propagated:
        When a cached answer is returned, assert GeneratedAnswer.cache_hit=True.

Dependencies:
    - pytest
    - pytest-asyncio
    - unittest.mock (AsyncMock, MagicMock, patch)
    - app.pipeline.rag_pipeline (RAGPipeline)
    - tests.conftest (fixtures: mock_session_store, mock_rag_chain,
                      mock_retriever, mock_reranker, mock_memory_manager,
                      mock_embedding_cache, mock_response_cache)
"""
