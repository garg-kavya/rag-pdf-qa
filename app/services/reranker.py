"""
Reranking Service
==================

Purpose:
    Applies a second-pass semantic reranker to the threshold-filtered
    candidates produced by RetrieverService.retrieve(). Produces a more
    accurate relevance ordering before MMR diversity selection is applied.

    IMPORTANT — exact position in the pipeline (owned by RAGPipeline):

        RetrieverService.retrieve()         stage 1+2: vector search + threshold
            ↓  list[ScoredChunk]  (bi_encoder_score set)
        RerankerService.rerank()            stage 3a: cross-encoder reranking
            ↓  list[ScoredChunk]  (similarity_score updated, rerank_score set)
        RetrieverService.apply_mmr()        stage 3b: diversity selection
            ↓  final top_k list[ScoredChunk]
        RAGChain.invoke()                   LLM generation

Why a Dedicated Reranker:
    RetrieverService MMR (stage 3b) addresses *diversity* — it prevents
    returning N near-identical chunks. It does not improve relevance ordering.

    RerankerService addresses *relevance precision* — it scores (query, chunk)
    pairs jointly using the full text of both, which is fundamentally more
    accurate than bi-encoder cosine similarity.

    The two-stage design (bi-encoder + cross-encoder) is the standard
    production approach: the fast bi-encoder narrows the candidate pool;
    the slow cross-encoder provides high-quality scoring on the smaller set.

Score Contract:
    Input chunks have:
        bi_encoder_score  — cosine similarity from vector search (already set)
        similarity_score  — equals bi_encoder_score at this point

    Output chunks have:
        bi_encoder_score  — unchanged (preserved for diagnostics)
        rerank_score      — raw score from cross-encoder or Cohere API
        similarity_score  — set to normalised(rerank_score) for downstream use
                            (MMR uses similarity_score for cross-similarity calc)

    If reranker is disabled (RERANKER_BACKEND="none"), this service is a
    no-op: chunks pass through unchanged and RAGPipeline skips the call
    entirely (guarded by is_enabled()).

Backend Options:

    "none"
        Disabled. Default when RERANKER_BACKEND is not configured.
        is_enabled() returns False; RAGPipeline does not call rerank().

    "cross_encoder"
        Local sentence-transformers CrossEncoder.
        Model: CROSS_ENCODER_MODEL (default "cross-encoder/ms-marco-MiniLM-L-6-v2")
        Latency: ~50-150ms for 10 candidates on CPU.
        No API cost. Recommended for development / air-gapped environments.

    "cohere"
        Cohere Rerank API.
        Latency: ~200-400ms.
        Cost: ~$1 per 1000 calls.
        Recommended for production (higher quality than local cross-encoder).

Methods:

    rerank(
        query_text: str,
        candidates: list[ScoredChunk]
    ) -> list[ScoredChunk]:
        Re-scores and re-orders candidates against the query.
        Inputs:
            query_text  — standalone query string (NOT its embedding)
            candidates  — threshold-filtered list from RetrieverService.retrieve()
        Outputs:
            list[ScoredChunk] in descending relevance order.
            similarity_score updated; bi_encoder_score and rerank_score set.
        Edge cases:
            - len(candidates) == 0: returns empty list immediately.
            - len(candidates) == 1: returns list unchanged (no reranking needed).
        Raises:
            RerankerError — backend call failed; RAGPipeline catches this and
                            falls back to bi-encoder ordering (logs a warning).

    is_enabled() -> bool:
        Returns True if RERANKER_BACKEND != "none".
        Called by RAGPipeline to guard the reranking step.

Latency Budget:
    Cohere:       +200-400ms
    CrossEncoder: +50-150ms
    Combined with streaming, total time to first token remains ≤ 2s.

Dependencies:
    cohere                          (if RERANKER_BACKEND == "cohere")
    sentence-transformers           (if RERANKER_BACKEND == "cross_encoder")
    app.models.query                (ScoredChunk)
    app.exceptions                  (RerankerError)
    app.config                      (RerankerSettings)
"""
