"""Ingestion Pipeline — PDF → parse → clean → chunk → embed → store."""
from __future__ import annotations

import time

from app.db.document_registry import DocumentRegistry
from app.db.session_store import SessionStore
from app.db.vector_store import VectorStore
from app.exceptions import EmbeddingAPIError, PDFParsingError, StorageWriteError
from app.schemas.metadata import IngestionMetadata
from app.services.chunker import ChunkerService
from app.services.embedder import EmbedderService
from app.services.pdf_processor import PDFProcessorService
from app.services.text_cleaner import TextCleanerService
from app.utils.logging import get_logger
from langsmith import traceable

logger = get_logger(__name__)


class IngestionPipeline:

    def __init__(
        self,
        pdf_processor: PDFProcessorService,
        text_cleaner: TextCleanerService,
        chunker: ChunkerService,
        embedder: EmbedderService,
        vector_store: VectorStore,
        document_registry: DocumentRegistry,
        session_store: SessionStore,
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        self._pdf = pdf_processor
        self._cleaner = text_cleaner
        self._chunker = chunker
        self._embedder = embedder
        self._store = vector_store
        self._registry = document_registry
        self._sessions = session_store
        self._embedding_model = embedding_model

    @traceable(name="pdf-ingestion", run_type="chain")
    async def run(
        self,
        file_path: str,
        document_id: str,
        filename: str,
        session_id: str | None = None,
    ) -> IngestionMetadata:
        t0 = time.monotonic()
        logger.info("Starting ingestion for %s", filename, extra={"document_id": document_id})

        # Step 1 — status → processing
        await self._registry.update_status(document_id, "processing")

        # Step 2 — PDF parsing
        try:
            parsed = self._pdf.parse(file_path, document_id)
        except PDFParsingError as exc:
            await self._registry.update_status(document_id, "error", exc.message)
            raise

        # Step 3 — Text cleaning
        cleaned_text, page_boundary_offsets = self._cleaner.clean(parsed)

        # Step 4 — Chunking
        chunks = self._chunker.chunk(
            cleaned_text=cleaned_text,
            page_boundary_offsets=page_boundary_offsets,
            document_id=document_id,
            document_name=filename,
        )
        logger.info("Created %d chunks", len(chunks), extra={"document_id": document_id})

        if not chunks:
            await self._registry.update_status(
                document_id, "error", "No text chunks could be created from this PDF."
            )
            raise PDFParsingError("PDF produced no usable text chunks after cleaning.")

        # Step 5 — Batch embedding
        try:
            chunks = await self._embedder.embed_chunks(chunks)
        except (EmbeddingAPIError, Exception) as exc:
            await self._registry.update_status(document_id, "error", str(exc))
            raise

        # Step 6 — Vector storage
        try:
            await self._store.add_chunks(chunks)
            await self._store.save_to_disk()
        except StorageWriteError as exc:
            await self._registry.update_status(document_id, "error", str(exc))
            raise

        elapsed_ms = (time.monotonic() - t0) * 1000

        # Step 7 — status → ready + metadata
        ingestion_meta = IngestionMetadata(
            document_id=document_id,
            filename=filename,
            page_count=parsed.pdf_metadata.page_count,
            total_chunks=len(chunks),
            total_tokens=sum(c.token_count for c in chunks),
            parser_used=parsed.parser_used,
            ingestion_time_ms=elapsed_ms,
            embedding_model=self._embedding_model,
        )
        await self._registry.update_status(document_id, "ready")
        await self._registry.set_ingestion_metadata(
            document_id, parsed.pdf_metadata, ingestion_meta
        )

        logger.info(
            "Ingestion complete: %d chunks, %.0fms",
            len(chunks), elapsed_ms,
            extra={"document_id": document_id},
        )

        # Step 8 — Session association (optional)
        if session_id:
            await self._sessions.add_document_to_session(session_id, document_id)

        return ingestion_meta
