"""Query endpoints — sync and streaming."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.dependencies import get_current_user, get_rag_pipeline
from app.models.user import User
from app.pipeline.rag_pipeline import RAGPipeline
from app.schemas.query import (
    CitationSchema,
    PipelineMetadataSchema,
    QueryRequest,
    QueryResponse,
    RetrievalMetadataSchema,
)
from app.services.streaming import StreamingHandler

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    pipeline: RAGPipeline = Depends(get_rag_pipeline),
    current_user: User = Depends(get_current_user),
):
    answer = await pipeline.run(
        raw_query=body.question,
        session_id=body.session_id,
        document_ids=body.document_ids,
        top_k=body.top_k,
    )

    citations = [
        CitationSchema(
            document_name=c.document_name,
            page_numbers=c.page_numbers,
            chunk_index=c.chunk_index,
            chunk_id=c.chunk_id,
            excerpt=c.excerpt,
        )
        for c in answer.citations
    ]

    pm = answer.pipeline_metadata
    pipeline_meta = PipelineMetadataSchema(
        total_time_ms=pm.total_time_ms,
        reformulation_time_ms=pm.reformulation_time_ms,
        embedding_time_ms=pm.embedding_time_ms,
        retrieval_time_ms=pm.retrieval_time_ms,
        reranking_time_ms=pm.reranking_time_ms,
        mmr_time_ms=pm.mmr_time_ms,
        generation_time_ms=pm.generation_time_ms,
        memory_read_time_ms=pm.memory_read_time_ms,
        memory_write_time_ms=pm.memory_write_time_ms,
        embedding_cache_hit=pm.embedding_cache_hit,
        response_cache_hit=pm.response_cache_hit,
        reranker_backend=pm.reranker_backend,
        llm_model=pm.llm_model,
        embedding_model=pm.embedding_model,
    ) if pm else None

    rm = answer.retrieval_context.retrieval_metadata if answer.retrieval_context else None
    retrieval_meta = RetrievalMetadataSchema(
        retrieval_time_ms=rm.retrieval_time_ms,
        candidates_considered=rm.candidates_considered,
        candidates_after_threshold=rm.candidates_after_threshold,
        chunks_used=rm.chunks_used,
        mmr_applied=rm.mmr_applied,
        reranker_applied=rm.reranker_applied,
        similarity_scores=rm.similarity_scores,
        top_k_requested=rm.top_k_requested,
        similarity_threshold_used=rm.similarity_threshold_used,
    ) if rm else None

    return QueryResponse(
        answer=answer.answer_text,
        citations=citations,
        session_id=body.session_id,
        query_id=answer.query_id,
        confidence=answer.confidence,
        cache_hit=answer.cache_hit,
        retrieval_metadata=retrieval_meta,
        pipeline_metadata=pipeline_meta,
    )


@router.post("/query/stream")
async def query_stream(
    body: QueryRequest,
    pipeline: RAGPipeline = Depends(get_rag_pipeline),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    query_id_holder: list[str] = ["unknown"]

    async def _gen():
        async for chunk in pipeline.run_stream(
            raw_query=body.question,
            session_id=body.session_id,
            document_ids=body.document_ids,
            top_k=body.top_k,
        ):
            if chunk.event == "done":
                query_id_holder[0] = chunk.data.get("query_id", "unknown")
            yield chunk

    return StreamingHandler.create_stream_response(
        token_generator=_gen(),
        query_id=query_id_holder[0],
    )
