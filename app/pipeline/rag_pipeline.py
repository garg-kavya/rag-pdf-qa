"""RAG Pipeline — central query orchestrator."""
from __future__ import annotations

import time
import uuid
from typing import AsyncGenerator

from langsmith import traceable

from app.cache.embedding_cache import EmbeddingCache
from app.cache.response_cache import ResponseCache
from app.chains.rag_chain import RAGChain
from app.config import Settings
from app.db.session_store import SessionStore
from app.exceptions import (
    NoDocumentsError,
    RerankerError,
    SessionExpiredError,
    SessionNotFoundError,
)
from app.memory.memory_manager import MemoryManager
from app.models.query import (
    GeneratedAnswer,
    PipelineMetadata,
    QueryContext,
    RetrievedContext,
    StreamingChunk,
)
from app.schemas.metadata import RetrievalMetadata
from app.services.query_reformulator import QueryReformulator
from app.services.reranker import RerankerService
from app.services.retriever import RetrieverService
from app.utils.logging import get_logger

logger = get_logger(__name__)


class RAGPipeline:

    def __init__(
        self,
        session_store: SessionStore,
        response_cache: ResponseCache,
        embedding_cache: EmbeddingCache,
        reformulator: QueryReformulator,
        retriever: RetrieverService,
        reranker: RerankerService,
        memory_manager: MemoryManager,
        rag_chain: RAGChain,
        settings: Settings,
    ) -> None:
        self._sessions = session_store
        self._response_cache = response_cache
        self._embedding_cache = embedding_cache
        self._reformulator = reformulator
        self._retriever = retriever
        self._reranker = reranker
        self._memory = memory_manager
        self._chain = rag_chain
        self._settings = settings

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @traceable(name="rag-query", run_type="chain")
    async def run(
        self,
        raw_query: str,
        session_id: str,
        document_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> GeneratedAnswer:
        """Full non-streaming pipeline. Consults and stores ResponseCache."""
        t_total = time.monotonic()
        query_id = str(uuid.uuid4())

        # Step 1 — validate session
        session = await self._sessions.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session {session_id} not found or expired.")
        doc_ids = document_ids or session.document_ids
        if not doc_ids:
            raise NoDocumentsError("Session has no documents to query.")

        # Step 2 — response cache check
        async def generate_fn() -> GeneratedAnswer:
            return await self._run_pipeline(
                raw_query, session_id, doc_ids, top_k, query_id, t_total
            )

        answer = await self._response_cache.get_or_generate(
            query_text=raw_query,
            session_id=session_id,
            document_ids=doc_ids,
            turn_count=session.turn_count,
            generate_fn=generate_fn,
        )
        return answer

    @traceable(name="rag-query-stream", run_type="chain")
    async def run_stream(
        self,
        raw_query: str,
        session_id: str,
        document_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> AsyncGenerator[StreamingChunk, None]:
        """Streaming pipeline — yields SSE events, skips ResponseCache."""
        t_total = time.monotonic()
        query_id = str(uuid.uuid4())

        session = await self._sessions.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session {session_id} not found or expired.")
        doc_ids = document_ids or session.document_ids
        if not doc_ids:
            raise NoDocumentsError("Session has no documents to query.")

        query_ctx, retrieved_ctx = await self._prepare_context(
            raw_query, session_id, doc_ids, top_k, query_id
        )

        full_text = ""
        final_citations = []

        try:
            async for chunk in self._chain.stream(query_ctx, retrieved_ctx):
                if chunk.event == "token":
                    full_text += chunk.data.get("text", "")
                    yield chunk
                elif chunk.event == "citation":
                    final_citations = chunk.data.get("citations", [])
                    yield chunk
        except Exception as exc:
            yield StreamingChunk(
                event="error",
                data={"message": str(exc), "query_id": query_id},
            )
            return

        elapsed_ms = (time.monotonic() - t_total) * 1000

        # Compute confidence from retrieved chunk scores (mirrors RAGChain._compute_confidence)
        chunks = retrieved_ctx.chunks
        if chunks:
            mean_score = sum(sc.similarity_score for sc in chunks) / len(chunks)
            _SCORE_MIN, _SCORE_MAX = 0.10, 0.55
            normalized = max(0.0, min(1.0, (mean_score - _SCORE_MIN) / (_SCORE_MAX - _SCORE_MIN)))
            citation_factor = min(1.0, len(final_citations) / max(len(chunks), 1))
            confidence = round(min(1.0, normalized * (0.7 + 0.3 * citation_factor)), 3)
        else:
            confidence = 0.0

        yield StreamingChunk(
            event="done",
            data={
                "query_id": query_id,
                "total_tokens": len(full_text.split()),
                "retrieval_time_ms": retrieved_ctx.retrieval_metadata.retrieval_time_ms,
                "reranker_applied": query_ctx.reranker_applied,
                "confidence": confidence,
            },
        )

        # Step 11 — memory write after stream exhausted
        from app.models.query import Citation
        citations_obj = [
            Citation(
                document_name=c["document_name"],
                page_numbers=c["page_numbers"],
                chunk_index=c["chunk_index"],
                chunk_id=c["chunk_id"],
                excerpt=c["excerpt"],
            )
            for c in final_citations
        ]
        await self._memory.record_turn(
            session_id=session_id,
            user_query=raw_query,
            standalone_query=query_ctx.standalone_query,
            assistant_response=full_text,
            retrieved_chunk_ids=[sc.chunk.chunk_id for sc in retrieved_ctx.chunks],
            citations=citations_obj,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _prepare_context(
        self,
        raw_query: str,
        session_id: str,
        doc_ids: list[str],
        top_k: int | None,
        query_id: str,
    ) -> tuple[QueryContext, RetrievedContext]:
        """Steps 3–9: reformulation → embedding → retrieval → reranking → MMR → memory."""
        session = await self._sessions.get_session(session_id)
        history = session.conversation_history if session else []

        # Step 3 — reformulation (always run to expand inferential queries)
        t0 = time.monotonic()
        standalone_query = await self._reformulator.reformulate(raw_query, history)
        reformulation_ms = (time.monotonic() - t0) * 1000

        # Step 4 — embedding (via cache)
        t0 = time.monotonic()
        query_embedding = await self._embedding_cache.get_or_embed(standalone_query)
        embedding_ms = (time.monotonic() - t0) * 1000

        # Step 5 — retrieval (vector search + threshold)
        t0 = time.monotonic()
        candidates, retrieval_meta = await self._retriever.retrieve(
            query_embedding=query_embedding,
            document_ids=doc_ids,
            query_text=standalone_query,
            top_k_candidates=self._settings.top_k_candidates,
        )
        retrieval_ms = (time.monotonic() - t0) * 1000

        # Step 6 — reranking (conditional)
        reranker_applied = False
        reranking_ms = 0.0
        if self._reranker.is_enabled() and candidates:
            t0 = time.monotonic()
            try:
                candidates = await self._reranker.rerank(standalone_query, candidates)
                reranker_applied = True
            except RerankerError as exc:
                logger.warning("Reranker failed, falling back to bi-encoder: %s", exc)
            reranking_ms = (time.monotonic() - t0) * 1000

        # Step 7 — MMR diversity selection
        t0 = time.monotonic()
        k = top_k or self._settings.top_k
        final_chunks = self._retriever.apply_mmr(candidates, top_k=k)
        mmr_ms = (time.monotonic() - t0) * 1000

        # Fill retrieval metadata
        retrieval_meta.reranker_applied = reranker_applied
        retrieval_meta.chunks_used = len(final_chunks)
        retrieval_meta.mmr_applied = len(candidates) > k
        retrieval_meta.similarity_scores = [sc.similarity_score for sc in final_chunks]
        retrieval_meta.retrieval_time_ms = retrieval_ms

        # Step 8 — memory read
        t0 = time.monotonic()
        formatted_history = await self._memory.get_formatted_history(
            session_id, token_budget=self._settings.memory_token_budget
        )
        memory_read_ms = (time.monotonic() - t0) * 1000

        # Step 9 — assemble QueryContext
        query_ctx = QueryContext(
            raw_query=raw_query,
            standalone_query=standalone_query,
            query_id=query_id,
            session_id=session_id,
            document_ids=doc_ids,
            query_embedding=query_embedding,
            formatted_history=formatted_history,
            reranker_applied=reranker_applied,
            cache_hit=False,
        )
        retrieved_ctx = RetrievedContext(chunks=final_chunks, retrieval_metadata=retrieval_meta)

        return query_ctx, retrieved_ctx

    async def _run_pipeline(
        self,
        raw_query: str,
        session_id: str,
        doc_ids: list[str],
        top_k: int | None,
        query_id: str,
        t_total: float,
    ) -> GeneratedAnswer:
        """Steps 3–11 for non-streaming path."""
        query_ctx, retrieved_ctx = await self._prepare_context(
            raw_query, session_id, doc_ids, top_k, query_id
        )

        # Step 10 — LLM generation
        t0 = time.monotonic()
        answer = await self._chain.invoke(query_ctx, retrieved_ctx)
        generation_ms = (time.monotonic() - t0) * 1000

        # Step 11 — memory write
        t0 = time.monotonic()
        await self._memory.record_turn(
            session_id=session_id,
            user_query=raw_query,
            standalone_query=query_ctx.standalone_query,
            assistant_response=answer.answer_text,
            retrieved_chunk_ids=[sc.chunk.chunk_id for sc in retrieved_ctx.chunks],
            citations=answer.citations,
        )
        memory_write_ms = (time.monotonic() - t0) * 1000

        total_ms = (time.monotonic() - t_total) * 1000
        meta = retrieved_ctx.retrieval_metadata

        answer.query_id = query_id
        answer.cache_hit = False
        answer.retrieval_context = retrieved_ctx
        answer.pipeline_metadata = PipelineMetadata(
            query_id=query_id,
            total_time_ms=total_ms,
            generation_time_ms=generation_ms,
            memory_write_time_ms=memory_write_ms,
            retrieval_time_ms=meta.retrieval_time_ms,
            reranker_backend=self._settings.reranker_backend,
            llm_model=self._settings.llm_model,
            embedding_model=self._settings.embedding_model,
        )
        return answer
