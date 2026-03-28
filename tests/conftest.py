"""Shared pytest fixtures for the RAG PDF Q&A test suite."""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure a valid API key is available before any app import
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key-for-unit-tests")

from app.cache.in_memory_cache import InMemoryCache
from app.cache.response_cache import ResponseCache
from app.config import Settings
from app.db.document_registry import DocumentRegistry
from app.db.session_store import SessionStore
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.query import (
    Citation,
    GeneratedAnswer,
    PipelineMetadata,
    RetrievedContext,
    ScoredChunk,
    StreamingChunk,
)
from app.models.session import ConversationTurn, Session
from app.schemas.metadata import IngestionMetadata, RetrievalMetadata


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@pytest.fixture
def settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Minimal valid single-page PDF (contains extractable text via content stream)."""
    content_stream = (
        b"BT /F1 12 Tf 100 700 Td "
        b"(This is a sample PDF document created for testing purposes. "
        b"It contains sufficient text for extraction by PyMuPDF and pdfplumber.) Tj ET"
    )
    length = len(content_stream)
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(length).encode() + b" >>\nstream\n"
        + content_stream + b"\nendstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000274 00000 n \n"
        b"0000000400 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n470\n%%EOF"
    )
    return pdf


@pytest.fixture
def sample_pdf_file(tmp_path, sample_pdf_bytes):
    """Write minimal PDF to a temp file and return the path."""
    path = tmp_path / "test_document.pdf"
    path.write_bytes(sample_pdf_bytes)
    return str(path)


@pytest.fixture
def sample_document() -> Document:
    return Document(
        document_id=str(uuid.uuid4()),
        filename="test.pdf",
        file_path="/tmp/test.pdf",
        file_size_bytes=2048,
        status="ready",
        page_count=3,
        total_chunks=6,
    )


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    doc_id = str(uuid.uuid4())
    texts = [
        "Machine learning is a branch of artificial intelligence.",
        "Neural networks are inspired by biological brain structure.",
        "Deep learning uses multiple layers to learn representations.",
        "Transformers use attention mechanisms for sequence modelling.",
    ]
    return [
        Chunk(
            document_id=doc_id,
            document_name="test.pdf",
            chunk_index=i,
            text=texts[i],
            token_count=len(texts[i].split()),
            page_numbers=[i + 1],
            start_char_offset=i * 200,
            end_char_offset=(i + 1) * 200,
            embedding=[float(j % 100) / 100.0 for j in range(1536)],
        )
        for i in range(4)
    ]


@pytest.fixture
def retrieval_metadata() -> RetrievalMetadata:
    return RetrievalMetadata(
        retrieval_time_ms=12.5,
        candidates_considered=10,
        candidates_after_threshold=4,
        chunks_used=4,
        mmr_applied=True,
        reranker_applied=False,
        similarity_scores=[0.92, 0.88, 0.81, 0.75],
        top_k_requested=5,
        similarity_threshold_used=0.70,
    )


@pytest.fixture
def sample_citation() -> Citation:
    return Citation(
        document_name="test.pdf",
        page_numbers=[1],
        chunk_index=0,
        chunk_id=str(uuid.uuid4()),
        excerpt="Machine learning is a branch of artificial intelligence.",
    )


@pytest.fixture
def sample_generated_answer(sample_citation) -> GeneratedAnswer:
    meta = PipelineMetadata(query_id=str(uuid.uuid4()))
    return GeneratedAnswer(
        answer_text="Machine learning is a branch of AI. [Source 1]",
        citations=[sample_citation],
        confidence=0.88,
        query_id=meta.query_id,
        cache_hit=False,
        retrieval_context=None,
        pipeline_metadata=meta,
    )


# ---------------------------------------------------------------------------
# Mock service fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed_query = AsyncMock(return_value=[0.1] * 1536)

    async def _embed_chunks(chunks):
        for c in chunks:
            c.embedding = [0.1] * 1536
        return chunks

    embedder.embed_chunks = AsyncMock(side_effect=_embed_chunks)
    return embedder


@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    store.add_chunks = AsyncMock(return_value=None)
    store.delete_document = AsyncMock(return_value=3)
    store.get_collection_stats = AsyncMock(
        return_value={"total_vectors": 0, "total_documents": 0}
    )
    return store


@pytest.fixture
def mock_rag_chain(sample_generated_answer):
    chain = AsyncMock()
    chain.invoke = AsyncMock(return_value=sample_generated_answer)

    async def _stream(query_ctx, retrieved_ctx):
        yield StreamingChunk(event="token", data={"text": "Machine ", "query_id": "q1"})
        yield StreamingChunk(event="token", data={"text": "learning.", "query_id": "q1"})
        yield StreamingChunk(event="citation", data={"citations": [], "query_id": "q1"})

    chain.stream = MagicMock(side_effect=_stream)
    return chain


# ---------------------------------------------------------------------------
# Store fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session_store(settings) -> SessionStore:
    return SessionStore(settings)


@pytest.fixture
def document_registry() -> DocumentRegistry:
    return DocumentRegistry()


@pytest.fixture
async def sample_session(session_store) -> Session:
    return await session_store.create_session(["doc-1", "doc-2"])


@pytest.fixture
async def session_with_history(session_store) -> Session:
    session = await session_store.create_session(["doc-1"])
    turns = [
        ConversationTurn(
            user_query=f"Question {i}",
            standalone_query=f"Question {i}",
            assistant_response=f"Answer {i} [Source 1].",
            retrieved_chunk_ids=[str(uuid.uuid4())],
        )
        for i in range(3)
    ]
    for turn in turns:
        await session_store.update_session(session.session_id, turn)
    # Re-fetch the updated session
    return await session_store.get_session(session.session_id)


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest.fixture
async def test_client(tmp_path):
    """AsyncClient backed by the real FastAPI app with mocked external services."""
    from app.config import get_settings as _cached_get_settings
    from app.main import create_app
    from app import dependencies as _deps

    # Clear cached settings so env vars take effect
    _cached_get_settings.cache_clear()

    _app = create_app()

    # Build lightweight test counterparts
    _settings = Settings()
    _session_store = SessionStore(_settings)
    _doc_registry = DocumentRegistry()
    _vec_store = AsyncMock()
    _vec_store.get_collection_stats = AsyncMock(
        return_value={"total_vectors": 0, "total_documents": 0}
    )
    _vec_store.delete_document = AsyncMock(return_value=0)
    _vec_store.add_chunks = AsyncMock(return_value=None)
    _vec_store.search = AsyncMock(return_value=[])

    _resp_cache = ResponseCache(
        backend=InMemoryCache(max_size=256, default_ttl=60), ttl=60
    )

    _rag_pipeline = AsyncMock()
    _ingestion_pipeline = AsyncMock()
    _ingestion_pipeline.run = AsyncMock(
        return_value=IngestionMetadata(
            document_id="test-doc-id",
            filename="test.pdf",
            page_count=1,
            total_chunks=2,
            total_tokens=50,
            ingestion_time_ms=100.0,
        )
    )

    from app.models.user import User as _User
    _test_user = _User(email="test@example.com", hashed_password="hashed", user_id="test-user-id")

    _app.dependency_overrides[_deps.get_settings] = lambda: _settings
    _app.dependency_overrides[_deps.get_session_store] = lambda: _session_store
    _app.dependency_overrides[_deps.get_document_registry] = lambda: _doc_registry
    _app.dependency_overrides[_deps.get_vector_store] = lambda: _vec_store
    _app.dependency_overrides[_deps.get_response_cache] = lambda: _resp_cache
    _app.dependency_overrides[_deps.get_rag_pipeline] = lambda: _rag_pipeline
    _app.dependency_overrides[_deps.get_ingestion_pipeline] = lambda: _ingestion_pipeline
    _app.dependency_overrides[_deps.get_current_user] = lambda: _test_user

    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as client:
        client._test = SimpleNamespace(
            settings=_settings,
            session_store=_session_store,
            doc_registry=_doc_registry,
            vec_store=_vec_store,
            rag_pipeline=_rag_pipeline,
            ingestion_pipeline=_ingestion_pipeline,
        )
        yield client

    _app.dependency_overrides.clear()
    _cached_get_settings.cache_clear()
