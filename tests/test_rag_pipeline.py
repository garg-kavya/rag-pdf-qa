"""Tests for RAGPipeline — orchestration, caching, and error propagation."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cache.embedding_cache import EmbeddingCache
from app.cache.in_memory_cache import InMemoryCache
from app.cache.response_cache import ResponseCache
from app.db.session_store import SessionStore
from app.exceptions import NoDocumentsError, RerankerError, SessionNotFoundError
from app.memory.memory_manager import MemoryManager
from app.models.chunk import Chunk
from app.models.query import (
    Citation,
    GeneratedAnswer,
    PipelineMetadata,
    QueryContext,
    RetrievedContext,
    ScoredChunk,
    StreamingChunk,
)
from app.pipeline.rag_pipeline import RAGPipeline
from app.schemas.metadata import RetrievalMetadata
from app.services.query_reformulator import QueryReformulator
from app.services.reranker import RerankerService
from app.services.retriever import RetrieverService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(index: int = 0) -> Chunk:
    return Chunk(
        document_id="doc-1",
        document_name="test.pdf",
        chunk_index=index,
        text=f"Content chunk {index}.",
        token_count=5,
        page_numbers=[1],
        start_char_offset=index * 100,
        end_char_offset=(index + 1) * 100,
    )


def _make_scored(index: int = 0, score: float = 0.85) -> ScoredChunk:
    sc = ScoredChunk(
        chunk=_make_chunk(index),
        similarity_score=score,
        bi_encoder_score=score,
    )
    sc.rank = index + 1
    return sc


def _make_retrieval_meta() -> RetrievalMetadata:
    return RetrievalMetadata(
        retrieval_time_ms=5.0,
        candidates_considered=5,
        candidates_after_threshold=3,
        chunks_used=3,
        similarity_scores=[0.90, 0.85, 0.80],
        top_k_requested=5,
        similarity_threshold_used=0.70,
    )


def _make_answer(cache_hit: bool = False) -> GeneratedAnswer:
    qid = str(uuid.uuid4())
    return GeneratedAnswer(
        answer_text="Answer [Source 1].",
        citations=[Citation(
            document_name="test.pdf",
            page_numbers=[1],
            chunk_index=0,
            chunk_id=str(uuid.uuid4()),
            excerpt="Content.",
        )],
        confidence=0.85,
        query_id=qid,
        cache_hit=cache_hit,
        retrieval_context=None,
        pipeline_metadata=PipelineMetadata(query_id=qid),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session_store():
    store = AsyncMock(spec=SessionStore)
    return store


@pytest.fixture
def mock_reformulator():
    ref = AsyncMock(spec=QueryReformulator)
    ref.reformulate = AsyncMock(side_effect=lambda q, hist: q)  # identity
    return ref


@pytest.fixture
def mock_embedding_cache():
    cache = AsyncMock(spec=EmbeddingCache)
    cache.get_or_embed = AsyncMock(return_value=[0.1] * 1536)
    return cache


@pytest.fixture
def mock_retriever():
    ret = AsyncMock(spec=RetrieverService)
    scored = [_make_scored(i) for i in range(3)]
    meta = _make_retrieval_meta()
    ret.retrieve = AsyncMock(return_value=(scored, meta))
    ret.apply_mmr = MagicMock(return_value=scored)
    return ret


@pytest.fixture
def mock_reranker():
    rr = AsyncMock(spec=RerankerService)
    rr.is_enabled = MagicMock(return_value=False)
    rr.rerank = AsyncMock(side_effect=lambda q, c: c)
    return rr


@pytest.fixture
def mock_memory_manager():
    mm = AsyncMock(spec=MemoryManager)
    mm.get_formatted_history = AsyncMock(return_value="")
    mm.record_turn = AsyncMock(return_value=None)
    mm.get_turn_count = AsyncMock(return_value=0)
    return mm


@pytest.fixture
def mock_rag_chain(sample_generated_answer):
    chain = AsyncMock()
    chain.invoke = AsyncMock(return_value=sample_generated_answer)

    async def _stream(qc, rc):
        yield StreamingChunk(event="token", data={"text": "Hello", "query_id": "q1"})
        yield StreamingChunk(event="citation", data={"citations": [], "query_id": "q1"})

    chain.stream = MagicMock(side_effect=_stream)
    return chain


@pytest.fixture
def mock_response_cache():
    cache = AsyncMock(spec=ResponseCache)

    async def _get_or_generate(*a, generate_fn, **kw):
        return await generate_fn()

    cache.get_or_generate = AsyncMock(side_effect=_get_or_generate)
    cache.invalidate_session = AsyncMock()
    return cache


@pytest.fixture
def pipeline(settings, mock_session_store, mock_response_cache, mock_embedding_cache,
             mock_reformulator, mock_retriever, mock_reranker, mock_memory_manager,
             mock_rag_chain, session_store) -> RAGPipeline:
    # Use a real session on the mock_session_store
    session = MagicMock()
    session.session_id = "session-1"
    session.document_ids = ["doc-1"]
    session.conversation_history = []
    session.turn_count = 0
    mock_session_store.get_session = AsyncMock(return_value=session)

    return RAGPipeline(
        session_store=mock_session_store,
        response_cache=mock_response_cache,
        embedding_cache=mock_embedding_cache,
        reformulator=mock_reformulator,
        retriever=mock_retriever,
        reranker=mock_reranker,
        memory_manager=mock_memory_manager,
        rag_chain=mock_rag_chain,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# run() — non-streaming
# ---------------------------------------------------------------------------

async def test_run_session_not_found_raises(pipeline, mock_session_store):
    mock_session_store.get_session = AsyncMock(return_value=None)
    with pytest.raises(SessionNotFoundError):
        await pipeline.run("question", "nonexistent-session")


async def test_run_no_documents_raises(pipeline, mock_session_store):
    session = MagicMock()
    session.document_ids = []
    session.conversation_history = []
    session.turn_count = 0
    mock_session_store.get_session = AsyncMock(return_value=session)
    with pytest.raises(NoDocumentsError):
        await pipeline.run("question", "session-1")


async def test_run_calls_response_cache(pipeline, mock_response_cache):
    await pipeline.run("question", "session-1", document_ids=["doc-1"])
    mock_response_cache.get_or_generate.assert_called_once()


async def test_run_first_turn_still_reformulates(pipeline, mock_session_store,
                                                  mock_reformulator):
    """Reformulation now runs on every turn (including first) to expand inferential queries."""
    session = MagicMock()
    session.document_ids = ["doc-1"]
    session.conversation_history = []
    session.turn_count = 0
    mock_session_store.get_session = AsyncMock(return_value=session)

    await pipeline.run("question", "session-1", document_ids=["doc-1"])

    mock_reformulator.reformulate.assert_called_once()


async def test_run_follow_up_calls_reformulation(pipeline, mock_session_store,
                                                  mock_reformulator):
    from app.models.session import ConversationTurn
    session = MagicMock()
    session.document_ids = ["doc-1"]
    session.conversation_history = [
        ConversationTurn("prev Q", "prev Q", "prev A", [])
    ]
    session.turn_count = 1
    mock_session_store.get_session = AsyncMock(return_value=session)

    await pipeline.run("follow-up", "session-1", document_ids=["doc-1"])

    mock_reformulator.reformulate.assert_called_once()


async def test_run_embedding_uses_cache(pipeline, mock_embedding_cache):
    await pipeline.run("question", "session-1", document_ids=["doc-1"])
    mock_embedding_cache.get_or_embed.assert_called()


async def test_run_retriever_called_with_embedding(pipeline, mock_retriever,
                                                    mock_embedding_cache):
    mock_embedding_cache.get_or_embed = AsyncMock(return_value=[0.5] * 1536)
    await pipeline.run("question", "session-1", document_ids=["doc-1"])
    call_kwargs = mock_retriever.retrieve.call_args
    assert list(call_kwargs.kwargs["query_embedding"]) == [0.5] * 1536


async def test_run_reranker_skipped_when_disabled(pipeline, mock_reranker):
    mock_reranker.is_enabled = MagicMock(return_value=False)
    await pipeline.run("question", "session-1", document_ids=["doc-1"])
    mock_reranker.rerank.assert_not_called()


async def test_run_reranker_called_when_enabled(pipeline, mock_reranker):
    mock_reranker.is_enabled = MagicMock(return_value=True)
    await pipeline.run("question", "session-1", document_ids=["doc-1"])
    mock_reranker.rerank.assert_called_once()


async def test_run_memory_read_before_generation(pipeline, mock_memory_manager,
                                                  mock_rag_chain):
    call_order = []
    mock_memory_manager.get_formatted_history = AsyncMock(
        side_effect=lambda *a, **kw: call_order.append("memory_read") or ""
    )
    mock_rag_chain.invoke = AsyncMock(
        side_effect=lambda *a, **kw: (call_order.append("generation"), _make_answer())[1]
    )

    await pipeline.run("question", "session-1", document_ids=["doc-1"])

    assert call_order.index("memory_read") < call_order.index("generation")


async def test_run_memory_write_after_generation(pipeline, mock_memory_manager,
                                                  mock_rag_chain):
    call_order = []
    mock_rag_chain.invoke = AsyncMock(
        side_effect=lambda *a, **kw: (call_order.append("generation"), _make_answer())[1]
    )
    mock_memory_manager.record_turn = AsyncMock(
        side_effect=lambda *a, **kw: call_order.append("memory_write")
    )

    await pipeline.run("question", "session-1", document_ids=["doc-1"])

    assert call_order.index("generation") < call_order.index("memory_write")


async def test_run_reranker_error_fallback_to_bi_encoder(pipeline, mock_reranker):
    mock_reranker.is_enabled = MagicMock(return_value=True)
    mock_reranker.rerank = AsyncMock(side_effect=RerankerError("reranker down"))

    # Should NOT raise — falls back silently
    answer = await pipeline.run("question", "session-1", document_ids=["doc-1"])
    assert answer is not None


# ---------------------------------------------------------------------------
# run_stream()
# ---------------------------------------------------------------------------

async def test_run_stream_yields_token_events(pipeline):
    events = []
    async for chunk in pipeline.run_stream("q", "session-1", document_ids=["doc-1"]):
        events.append(chunk)

    token_events = [e for e in events if e.event == "token"]
    assert len(token_events) >= 1


async def test_run_stream_yields_done_event(pipeline):
    events = []
    async for chunk in pipeline.run_stream("q", "session-1", document_ids=["doc-1"]):
        events.append(chunk)

    assert events[-1].event == "done"


async def test_run_stream_skips_response_cache(pipeline, mock_response_cache):
    async for _ in pipeline.run_stream("q", "session-1", document_ids=["doc-1"]):
        pass
    mock_response_cache.get_or_generate.assert_not_called()


async def test_run_stream_memory_write_after_stream_exhausted(pipeline,
                                                               mock_memory_manager):
    all_events = []
    async for chunk in pipeline.run_stream("q", "session-1", document_ids=["doc-1"]):
        all_events.append(chunk)

    # Memory write happens after the async for loop completes
    mock_memory_manager.record_turn.assert_called_once()


async def test_run_stream_session_not_found_raises(pipeline, mock_session_store):
    mock_session_store.get_session = AsyncMock(return_value=None)
    with pytest.raises(SessionNotFoundError):
        async for _ in pipeline.run_stream("q", "no-session"):
            pass
