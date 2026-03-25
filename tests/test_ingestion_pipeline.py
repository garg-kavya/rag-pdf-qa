"""
Ingestion Pipeline Tests
=========================

Purpose:
    Tests for the IngestionPipeline orchestrator. Verifies that all ingestion
    stages are called in order and that errors in any stage update document
    status correctly.

Test Cases:

    test_successful_ingestion_produces_ready_status:
        Run the full pipeline with a valid PDF; assert final document status
        is "ready" and ingestion_metadata is populated.

    test_stage_order_parse_clean_chunk_embed_store:
        Assert services are called in the correct order:
        parse → clean → chunk → embed → store.

    test_pdf_parsing_error_sets_error_status:
        When PDFProcessorService raises PDFParsingError, assert document
        status is set to "error" and error_message is populated.

    test_embedding_error_sets_error_status:
        When EmbedderService raises EmbeddingAPIError, assert document
        status is set to "error".

    test_vector_store_write_error_sets_error_status:
        When VectorStore.add_chunks() raises StorageWriteError, assert
        document status is set to "error".

    test_chunk_metadata_uses_typed_schema:
        Assert that ChunkMetadata objects (not raw dicts) are used when
        adding chunks to the vector store.

    test_session_association_when_session_id_provided:
        When session_id is passed to run(), assert
        SessionStore.add_document_to_session() is called.

    test_no_session_association_when_session_id_none:
        When session_id is None, assert SessionStore is not called.

    test_ingestion_metadata_contains_timing:
        Assert ingestion_metadata.ingestion_time_ms > 0.

    test_pdfplumber_fallback_triggered:
        When PyMuPDF returns low character count, assert pdfplumber
        fallback was used (parser_used="pdfplumber" in metadata).

Dependencies:
    - pytest
    - pytest-asyncio
    - unittest.mock
    - app.pipeline.ingestion_pipeline (IngestionPipeline)
    - tests.conftest (sample_pdf_bytes, mock services)
"""
