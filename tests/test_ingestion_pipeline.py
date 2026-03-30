"""Tests for IngestionPipeline — stage orchestration and error handling."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.document_registry import DocumentRegistry
from app.db.session_store import SessionStore
from app.exceptions import EmbeddingAPIError, PDFParsingError, StorageWriteError
from app.models.chunk import Chunk
from app.pipeline.ingestion_pipeline import IngestionPipeline
from app.schemas.metadata import IngestionMetadata, PDFMetadata
from app.services.chunker import ChunkerService
from app.services.embedder import EmbedderService
from app.services.pdf_processor import PDFProcessorService, PageContent, ParsedDocument
from app.services.table_extractor import TableExtractorService
from app.services.text_cleaner import TextCleanerService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parsed_document(doc_id: str = "doc-1", pages: int = 2) -> ParsedDocument:
    pdf_meta = PDFMetadata(
        page_count=pages,
        file_size_bytes=2048,
        parser_used="pymupdf",
    )
    page_list = [
        PageContent(page_number=i + 1, raw_text=f"Page {i+1} text content here.", char_count=30)
        for i in range(pages)
    ]
    return ParsedDocument(
        document_id=doc_id,
        pages=page_list,
        pdf_metadata=pdf_meta,
        parser_used="pymupdf",
    )


def _make_chunk(doc_id: str = "doc-1", index: int = 0) -> Chunk:
    c = Chunk(
        document_id=doc_id,
        document_name="test.pdf",
        chunk_index=index,
        text=f"Chunk {index} content.",
        token_count=5,
        page_numbers=[1],
        start_char_offset=index * 100,
        end_char_offset=(index + 1) * 100,
    )
    c.embedding = [0.1] * 1536
    return c


@pytest.fixture
def mock_pdf():
    svc = MagicMock(spec=PDFProcessorService)
    svc.parse = MagicMock(return_value=_make_parsed_document())
    return svc


@pytest.fixture
def mock_cleaner():
    svc = MagicMock(spec=TextCleanerService)
    svc.clean = MagicMock(return_value=("Cleaned text content.", [0]))
    return svc


@pytest.fixture
def mock_chunker():
    svc = MagicMock(spec=ChunkerService)
    svc.chunk = MagicMock(return_value=[_make_chunk(index=i) for i in range(3)])
    return svc


@pytest.fixture
def mock_embedder():
    svc = AsyncMock(spec=EmbedderService)

    async def embed(chunks):
        for c in chunks:
            c.embedding = [0.1] * 1536
        return chunks

    svc.embed_chunks = AsyncMock(side_effect=embed)
    return svc


@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.add_chunks = AsyncMock(return_value=None)
    return store


@pytest.fixture
def doc_registry() -> DocumentRegistry:
    return DocumentRegistry()


@pytest.fixture
def sess_store(settings) -> SessionStore:
    return SessionStore(settings)


@pytest.fixture
def pipeline(mock_pdf, mock_cleaner, mock_chunker, mock_embedder, mock_vector_store,
             doc_registry, sess_store) -> IngestionPipeline:
    return IngestionPipeline(
        pdf_processor=mock_pdf,
        text_cleaner=mock_cleaner,
        chunker=mock_chunker,
        embedder=mock_embedder,
        vector_store=mock_vector_store,
        document_registry=doc_registry,
        session_store=sess_store,
        embedding_model="text-embedding-3-small",
    )


# ---------------------------------------------------------------------------
# Successful ingestion
# ---------------------------------------------------------------------------

async def test_successful_ingestion_returns_metadata(pipeline, doc_registry):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)

    result = await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf")

    assert isinstance(result, IngestionMetadata)
    assert result.document_id == doc_id
    assert result.filename == "test.pdf"
    assert result.total_chunks == 3
    assert result.ingestion_time_ms > 0


async def test_successful_ingestion_sets_ready_status(pipeline, doc_registry):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)

    await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf")

    doc = await doc_registry.get(doc_id)
    assert doc.status == "ready"


async def test_ingestion_stage_order(pipeline, mock_pdf, mock_cleaner,
                                     mock_chunker, mock_embedder, mock_vector_store,
                                     doc_registry):
    """Verify that parse → clean → chunk → embed → store are called in order."""
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    call_order = []

    mock_pdf.parse = MagicMock(
        side_effect=lambda *a, **kw: (call_order.append("parse"), _make_parsed_document())[1]
    )
    mock_cleaner.clean = MagicMock(
        side_effect=lambda *a, **kw: (call_order.append("clean"), ("text", [0]))[1]
    )
    mock_chunker.chunk = MagicMock(
        side_effect=lambda *a, **kw: (call_order.append("chunk"), [_make_chunk()])[1]
    )

    async def _embed(chunks):
        call_order.append("embed")
        for c in chunks:
            c.embedding = [0.1] * 1536
        return chunks

    mock_embedder.embed_chunks = AsyncMock(side_effect=_embed)

    async def _store(chunks):
        call_order.append("store")

    mock_vector_store.add_chunks = AsyncMock(side_effect=_store)

    await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf")

    assert call_order == ["parse", "clean", "chunk", "embed", "store"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

async def test_pdf_parsing_error_sets_error_status(pipeline, mock_pdf, doc_registry):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "bad.pdf", "/tmp/bad.pdf", 512)
    mock_pdf.parse = MagicMock(side_effect=PDFParsingError("corrupt PDF"))

    with pytest.raises(PDFParsingError):
        await pipeline.run("/tmp/bad.pdf", doc_id, "bad.pdf")

    doc = await doc_registry.get(doc_id)
    assert doc.status == "error"


async def test_embedding_error_sets_error_status(pipeline, mock_embedder, doc_registry):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    mock_embedder.embed_chunks = AsyncMock(
        side_effect=EmbeddingAPIError("API quota exceeded")
    )

    with pytest.raises(Exception):
        await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf")

    doc = await doc_registry.get(doc_id)
    assert doc.status == "error"


async def test_vector_store_error_sets_error_status(pipeline, mock_vector_store, doc_registry):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    mock_vector_store.add_chunks = AsyncMock(
        side_effect=StorageWriteError("disk full")
    )

    with pytest.raises(StorageWriteError):
        await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf")

    doc = await doc_registry.get(doc_id)
    assert doc.status == "error"


# ---------------------------------------------------------------------------
# Session association
# ---------------------------------------------------------------------------

async def test_session_association_when_session_id_provided(pipeline, doc_registry, sess_store):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    session = await sess_store.create_session(["other-doc"])

    await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf", session_id=session.session_id)

    updated = await sess_store.get_session(session.session_id)
    assert doc_id in updated.document_ids


async def test_no_session_association_when_session_id_none(pipeline, doc_registry, sess_store):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    session = await sess_store.create_session(["other-doc"])

    await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf", session_id=None)

    updated = await sess_store.get_session(session.session_id)
    assert doc_id not in updated.document_ids


# ---------------------------------------------------------------------------
# Ingestion metadata
# ---------------------------------------------------------------------------

async def test_ingestion_metadata_page_count(pipeline, doc_registry, mock_pdf):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    mock_pdf.parse = MagicMock(return_value=_make_parsed_document(pages=5))

    result = await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf")

    assert result.page_count == 5


async def test_ingestion_metadata_parser_used(pipeline, doc_registry, mock_pdf):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    parsed = _make_parsed_document()
    parsed.parser_used = "pdfplumber"
    parsed.pdf_metadata = parsed.pdf_metadata.model_copy(update={"parser_used": "pdfplumber"})
    mock_pdf.parse = MagicMock(return_value=parsed)

    result = await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf")

    assert result.parser_used == "pdfplumber"


# ---------------------------------------------------------------------------
# Table extractor integration
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_table_extractor():
    svc = MagicMock(spec=TableExtractorService)
    # Returns 2 extra table chunks on top of whatever text chunks exist
    svc.extract = MagicMock(return_value=[_make_chunk(index=3), _make_chunk(index=4)])
    return svc


@pytest.fixture
def pipeline_with_extractor(
    mock_pdf, mock_cleaner, mock_chunker, mock_embedder,
    mock_vector_store, doc_registry, sess_store, mock_table_extractor,
) -> IngestionPipeline:
    return IngestionPipeline(
        pdf_processor=mock_pdf,
        text_cleaner=mock_cleaner,
        chunker=mock_chunker,
        embedder=mock_embedder,
        vector_store=mock_vector_store,
        document_registry=doc_registry,
        session_store=sess_store,
        embedding_model="text-embedding-3-small",
        table_extractor=mock_table_extractor,
    )


async def test_table_extractor_called_when_provided(
    pipeline_with_extractor, mock_table_extractor, doc_registry
):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    await pipeline_with_extractor.run("/tmp/test.pdf", doc_id, "test.pdf")
    mock_table_extractor.extract.assert_called_once()


async def test_table_extractor_receives_correct_file_path(
    pipeline_with_extractor, mock_table_extractor, doc_registry
):
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    await pipeline_with_extractor.run("/tmp/test.pdf", doc_id, "test.pdf")
    call_kwargs = mock_table_extractor.extract.call_args.kwargs
    assert call_kwargs["file_path"] == "/tmp/test.pdf"


async def test_table_extractor_start_index_equals_text_chunk_count(
    pipeline_with_extractor, mock_table_extractor, doc_registry
):
    """start_index passed to the extractor must equal the number of text chunks."""
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    # mock_chunker fixture returns 3 text chunks
    await pipeline_with_extractor.run("/tmp/test.pdf", doc_id, "test.pdf")
    call_kwargs = mock_table_extractor.extract.call_args.kwargs
    assert call_kwargs["start_index"] == 3


async def test_total_chunks_includes_table_chunks(pipeline_with_extractor, doc_registry):
    """result.total_chunks must count both text chunks and table chunks."""
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    result = await pipeline_with_extractor.run("/tmp/test.pdf", doc_id, "test.pdf")
    # mock_chunker → 3 text chunks, mock_table_extractor → 2 table chunks
    assert result.total_chunks == 5


async def test_table_extractor_none_does_not_raise(pipeline, doc_registry):
    """Default pipeline fixture has table_extractor=None; must run without error."""
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    result = await pipeline.run("/tmp/test.pdf", doc_id, "test.pdf")
    # Only the 3 text chunks from mock_chunker
    assert result.total_chunks == 3


async def test_table_extractor_empty_result_does_not_affect_pipeline(
    pipeline_with_extractor, mock_table_extractor, doc_registry
):
    """When table extractor returns [], pipeline should still succeed with text chunks only."""
    mock_table_extractor.extract = MagicMock(return_value=[])
    doc_id = str(uuid.uuid4())
    await doc_registry.register(doc_id, "test.pdf", "/tmp/test.pdf", 1024)
    result = await pipeline_with_extractor.run("/tmp/test.pdf", doc_id, "test.pdf")
    assert result.total_chunks == 3
