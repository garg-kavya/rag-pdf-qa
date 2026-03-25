"""
Retrieval Service
==================

Purpose:
    Performs semantic search over the vector database given a pre-computed
    query embedding, then applies score-threshold filtering and MMR diversity
    selection. Returns a ranked list of candidate chunks.

    IMPORTANT — scope of this service:
    ✓ Vector similarity search         (Stage 1)
    ✓ Score threshold filtering        (Stage 2)
    ✓ MMR diversity selection          (Stage 3, called separately)
    ✗ Query embedding                  → EmbeddingCache / EmbeddingService
    ✗ Cross-encoder reranking          → RerankerService
    ✗ Session or document validation   → RAGPipeline

    The full ordered pipeline (owned by RAGPipeline):
        EmbeddingCache.get_or_embed()         ← embedding
        RetrieverService.retrieve()           ← stages 1 + 2
        RerankerService.rerank()              ← optional, stage 3a
        RetrieverService.apply_mmr()          ← stage 3b (diversity)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stage Descriptions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Stage 1: Vector Similarity Search
        Input: query_embedding (pre-computed 1536-dim vector)
        Action: VectorStore.search(query_embedding, top_k=TOP_K_CANDIDATES,
                                   document_ids=document_ids)
        Returns: top TOP_K_CANDIDATES (query, chunk) cosine similarity pairs
        Latency: ~10-50ms (FAISS) / ~50-100ms (ChromaDB)
        Note: TOP_K_CANDIDATES = TOP_K * 2 (over-fetch for reranking/MMR)

    Stage 2: Score Threshold Filtering
        Input: list[ScoredChunk] from stage 1
        Action: discard any chunk where similarity_score < SIMILARITY_THRESHOLD
        Effect: prevents low-relevance chunks reaching later stages even if
                fewer than TOP_K_CANDIDATES remain after filtering
        Note: sets bi_encoder_score = similarity_score on each ScoredChunk

    Stage 3a (in RerankerService): Cross-Encoder Reranking (optional)
        Not performed here. RAGPipeline calls RerankerService.rerank() after
        retrieve() returns, if RERANKER_BACKEND != "none".

    Stage 3b: MMR Diversity Selection
        Input: list[ScoredChunk] (already reranked, or raw filtered if no reranker)
        Action: select final top_k chunks maximising:
                score = λ · similarity_score − (1−λ) · max_sim_to_selected
        Lambda: MMR_DIVERSITY_FACTOR (default 0.7 — favour relevance)
        Effect: eliminates near-duplicate chunks; ensures diverse coverage
        Latency: ~5-20ms (CPU, O(k·n) where n = candidates, k = top_k)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Methods
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    retrieve(
        query_embedding: list[float],
        document_ids: list[str],
        top_k_candidates: int | None = None
    ) -> tuple[list[ScoredChunk], RetrievalMetadata]:
        Executes stages 1 and 2. Returns threshold-filtered candidates
        ready for optional reranking and final MMR selection.
        Inputs:
            query_embedding   — 1536-dim pre-computed vector (caller's responsibility)
            document_ids      — scope search to these documents only
            top_k_candidates  — override candidate count; defaults to TOP_K_CANDIDATES
        Outputs:
            candidates: list[ScoredChunk] — filtered, NOT yet MMR-selected
                        Each chunk has bi_encoder_score set.
                        similarity_score == bi_encoder_score at this stage.
            metadata: RetrievalMetadata (partial — reranker_applied=False,
                        chunks_used=0; RAGPipeline fills these after MMR)
        Raises:
            StorageReadError   — vector store search failed
            NoDocumentsError   — document_ids is empty

    apply_mmr(
        candidates: list[ScoredChunk],
        top_k: int,
        diversity_factor: float | None = None
    ) -> list[ScoredChunk]:
        Executes stage 3b (MMR diversity selection) on already-reranked
        or threshold-filtered candidates.
        Inputs:
            candidates       — list[ScoredChunk] from retrieve() (+ optional reranking)
            top_k            — final number of chunks to return
            diversity_factor — override MMR lambda; defaults to MMR_DIVERSITY_FACTOR
        Outputs:
            list[ScoredChunk] of length ≤ top_k, in MMR-selected order.
            rank field is set on each chunk (1-based).
        Notes:
            - If len(candidates) <= top_k, returns all candidates without MMR
              (no diversity calculation needed).
            - Uses similarity_score (which may be reranker score) for
              both relevance and cross-similarity calculations.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Top-K Tuning Rationale
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Default: TOP_K=5 (final chunks to LLM), TOP_K_CANDIDATES=10 (over-fetch)

    - k=3: Simple factual lookups. Minimal context, fast, may miss evidence.
    - k=5: Default. 5 × 512 = ~2560 tokens; fits in 4K context budget.
    - k=7-10: Complex analytical questions requiring multi-section synthesis.
    - Configurable per-query via the API's top_k parameter (range 3-10).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Dependencies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    app.db.vector_store          (VectorStore interface)
    app.models.query             (ScoredChunk)
    app.schemas.metadata         (RetrievalMetadata)
    app.exceptions               (StorageReadError, NoDocumentsError)
    app.config                   (RetrievalSettings)
"""
