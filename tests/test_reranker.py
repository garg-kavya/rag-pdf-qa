"""
Reranker Service Tests
=======================

Purpose:
    Tests for the RerankerService, covering both backend variants
    (cross_encoder and cohere) using mocks.

Test Cases:

    test_rerank_orders_by_relevance:
        Given a query and candidates where one chunk is clearly more relevant,
        assert it is ranked first after reranking.

    test_rerank_updates_similarity_scores:
        After reranking, each ScoredChunk's similarity_score reflects the
        reranker's score (not the original bi-encoder score).

    test_bi_encoder_score_preserved:
        The original cosine similarity score is stored in bi_encoder_score
        for diagnostic purposes.

    test_top_n_truncation:
        When top_n=3 is passed and there are 6 candidates, only 3 are returned.

    test_rerank_with_top_n_none_returns_all:
        When top_n=None, all candidates are returned in reranked order.

    test_is_enabled_returns_false_when_backend_none:
        When RERANKER_BACKEND="none", is_enabled() returns False.

    test_is_enabled_returns_true_for_cross_encoder:
        When RERANKER_BACKEND="cross_encoder", is_enabled() returns True.

    test_reranker_error_propagates:
        When the backend raises an exception, a RerankerError is raised.

    test_single_candidate_not_reranked:
        With only one candidate, reranking returns it unchanged
        (avoids unnecessary API/model call).

    test_empty_candidates_returns_empty:
        Empty input returns empty output without calling the backend.

Dependencies:
    - pytest
    - pytest-asyncio
    - app.services.reranker
    - app.models.query (ScoredChunk)
    - app.exceptions (RerankerError)
    - unittest.mock (for Cohere and CrossEncoder mocks)
"""
