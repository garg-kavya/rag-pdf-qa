"""Retrieval Service — vector search, threshold filter, MMR."""
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
        top_k_candidates: int | None = None,
    ) -> tuple[list[ScoredChunk], RetrievalMetadata]:
        """Stage 1 (vector search) + Stage 2 (threshold filter)."""
        if not document_ids:
            raise NoDocumentsError("No documents to search.")

        fetch_k = top_k_candidates or self._top_k_candidates
        t0 = time.monotonic()

        try:
            raw = await self._store.search(query_embedding, top_k=fetch_k, document_ids=document_ids)
        except Exception as exc:
            raise StorageReadError(f"Vector search failed: {exc}") from exc

        elapsed_ms = (time.monotonic() - t0) * 1000

        # Threshold filter
        scored: list[ScoredChunk] = []
        for chunk, score in raw:
            if score >= self._threshold:
                scored.append(ScoredChunk(
                    chunk=chunk,
                    similarity_score=score,
                    bi_encoder_score=score,
                ))

        meta = RetrievalMetadata(
            retrieval_time_ms=elapsed_ms,
            candidates_considered=len(raw),
            candidates_after_threshold=len(scored),
            chunks_used=0,       # filled after MMR
            mmr_applied=False,   # filled after MMR
            reranker_applied=False,
            similarity_scores=[],
            top_k_requested=self._top_k,
            similarity_threshold_used=self._threshold,
        )

        logger.debug(
            "Retrieved %d/%d candidates above threshold %.2f",
            len(scored), len(raw), self._threshold,
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
