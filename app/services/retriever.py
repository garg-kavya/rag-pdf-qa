"""Retrieval Service — hybrid search (vector + BM25), threshold filter, MMR."""
from __future__ import annotations

import time

import numpy as np

from app.config import Settings
from app.db.vector_store import VectorStore
from app.exceptions import NoDocumentsError, StorageReadError
from app.models.query import RetrievedContext, ScoredChunk
from app.schemas.metadata import RetrievalMetadata
from app.utils.logging import get_logger

logger = get_logger(__name__)

# RRF constant — 60 is the standard value from the original paper.
_RRF_K = 60


def _reciprocal_rank_fusion(
    vector_results: list[ScoredChunk],
    keyword_results: list[ScoredChunk],
) -> list[ScoredChunk]:
    """Merge two ranked lists into one using Reciprocal Rank Fusion.

    score(d) = Σ 1 / (k + rank_i(d))

    Chunks appearing in both lists get a score from each; chunks in only
    one list still get their contribution. The merged list is sorted by
    combined RRF score descending.
    """
    rrf_scores: dict[str, float] = {}
    chunks: dict[str, ScoredChunk] = {}

    for rank, sc in enumerate(vector_results):
        cid = sc.chunk.chunk_id
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        chunks[cid] = sc

    for rank, sc in enumerate(keyword_results):
        cid = sc.chunk.chunk_id
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        if cid not in chunks:
            chunks[cid] = sc

    merged = sorted(chunks.values(), key=lambda sc: rrf_scores[sc.chunk.chunk_id], reverse=True)
    for sc in merged:
        sc.similarity_score = rrf_scores[sc.chunk.chunk_id]
    return merged


class RetrieverService:

    def __init__(self, vector_store: VectorStore, settings: Settings) -> None:
        self._store = vector_store
        self._top_k = settings.top_k
        self._top_k_candidates = settings.top_k_candidates
        self._threshold = settings.similarity_threshold
        self._mmr_lambda = settings.mmr_diversity_factor

    async def retrieve(
        self,
        query_embedding: list[float],
        document_ids: list[str],
        query_text: str = "",
        top_k_candidates: int | None = None,
    ) -> tuple[list[ScoredChunk], RetrievalMetadata]:
        """Hybrid retrieval: vector search + keyword search merged via RRF.

        Falls back to vector-only if keyword search returns nothing (e.g.
        very short queries or stores that don't support keyword search).
        """
        if not document_ids:
            raise NoDocumentsError("No documents to search.")

        fetch_k = top_k_candidates or self._top_k_candidates
        t0 = time.monotonic()

        # --- Stage 1a: semantic vector search ---
        try:
            vector_raw = await self._store.search(
                query_embedding, top_k=fetch_k, document_ids=document_ids
            )
        except Exception as exc:
            raise StorageReadError(f"Vector search failed: {exc}") from exc

        # --- Stage 1b: keyword search (BM25-style via PostgreSQL FTS) ---
        keyword_raw: list[tuple] = []
        if query_text.strip():
            try:
                keyword_raw = await self._store.keyword_search(
                    query_text, top_k=fetch_k, document_ids=document_ids
                )
            except Exception:
                logger.warning("Keyword search failed, falling back to vector-only")

        elapsed_ms = (time.monotonic() - t0) * 1000
        hybrid = bool(keyword_raw)

        # --- Stage 2: threshold filter on semantic results ---
        vector_scored = [
            ScoredChunk(chunk=chunk, similarity_score=score, bi_encoder_score=score)
            for chunk, score in vector_raw
            if score >= self._threshold
        ]
        keyword_scored = [
            ScoredChunk(chunk=chunk, similarity_score=score, bi_encoder_score=score)
            for chunk, score in keyword_raw
        ]

        # --- Stage 3: merge with Reciprocal Rank Fusion ---
        if hybrid:
            scored = _reciprocal_rank_fusion(vector_scored, keyword_scored)
            logger.debug(
                "Hybrid: %d vector + %d keyword → %d after RRF",
                len(vector_scored), len(keyword_scored), len(scored),
            )
        else:
            scored = vector_scored

        meta = RetrievalMetadata(
            retrieval_time_ms=elapsed_ms,
            candidates_considered=len(vector_raw) + len(keyword_raw),
            candidates_after_threshold=len(scored),
            chunks_used=0,
            mmr_applied=False,
            reranker_applied=False,
            hybrid_search_applied=hybrid,
            similarity_scores=[],
            top_k_requested=self._top_k,
            similarity_threshold_used=self._threshold,
        )

        logger.debug(
            "Retrieved %d candidates (hybrid=%s, %.0fms)",
            len(scored), hybrid, elapsed_ms,
        )
        return scored, meta

    def apply_mmr(
        self,
        candidates: list[ScoredChunk],
        top_k: int | None = None,
        diversity_factor: float | None = None,
    ) -> list[ScoredChunk]:
        """Stage 3b — Maximal Marginal Relevance diversity selection.

        Uses document_id + chunk_index distance as a diversity signal when
        embeddings are unavailable (they aren't stored after retrieval).
        Chunks from different documents or far-apart positions in the same
        document are treated as more diverse.
        """
        k = top_k or self._top_k
        lam = diversity_factor if diversity_factor is not None else self._mmr_lambda

        if len(candidates) <= k:
            for i, sc in enumerate(candidates):
                sc.rank = i + 1
            return candidates

        selected: list[ScoredChunk] = []
        remaining = list(candidates)

        while len(selected) < k and remaining:
            if not selected:
                best = max(remaining, key=lambda sc: sc.similarity_score)
            else:
                def mmr_score(sc: ScoredChunk) -> float:
                    rel = sc.similarity_score
                    # Cross-similarity: high if candidate is from the same
                    # document AND nearby chunk_index as an already-selected chunk
                    max_sim = 0.0
                    for sel in selected:
                        if sc.chunk.document_id == sel.chunk.document_id:
                            idx_dist = abs(sc.chunk.chunk_index - sel.chunk.chunk_index)
                            # Adjacent chunks (dist<=1) → sim=1.0, decays with distance
                            sim = 1.0 / (1.0 + idx_dist)
                        else:
                            sim = 0.0  # different documents → maximally diverse
                        max_sim = max(max_sim, sim)
                    return lam * rel - (1 - lam) * max_sim

                best = max(remaining, key=mmr_score)

            selected.append(best)
            remaining.remove(best)

        for i, sc in enumerate(selected):
            sc.rank = i + 1

        return selected
