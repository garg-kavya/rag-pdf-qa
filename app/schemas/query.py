"""
Query API Schemas
==================

Purpose:
    Pydantic models for the question-answering endpoints.
    Used by POST /api/v1/query and POST /api/v1/query/stream.

Schemas:

    QueryRequest:
        The user's question and configuration overrides.
        Fields:
            question: str       — required; 1-2000 characters
            session_id: str     — required; valid UUID of an active session
            document_ids: list[str] | None
                Optional override to scope retrieval to specific documents.
                If None, retrieval is scoped to all documents in the session.
            top_k: int | None   — optional; override retrieval top-k (range 3-10)
            stream: bool = False — ignored on /query; always True on /query/stream

    PipelineMetadataSchema:
        End-to-end timing and model diagnostics for the API response.
        Mirrors PipelineMetadata domain model for serialisation.
        Fields:
            total_time_ms: float
            reformulation_time_ms: float
            embedding_time_ms: float
            retrieval_time_ms: float
            reranking_time_ms: float
            generation_time_ms: float
            embedding_cache_hit: bool
            response_cache_hit: bool
            reranker_backend: str   — "cohere" | "cross_encoder" | "none"
            llm_model: str
            embedding_model: str

    CitationSchema:
        A single source reference in the response.
        Fields:
            document_name: str
            page_numbers: list[int]
            chunk_index: int
            chunk_id: str
            excerpt: str    — ≤200 characters

    RetrievalMetadataSchema:
        Diagnostics from the retrieval + reranking stages.
        Mirrors the typed RetrievalMetadata from app.schemas.metadata.
        Fields:
            retrieval_time_ms: float
            candidates_considered: int
            candidates_after_threshold: int
            chunks_used: int
            mmr_applied: bool
            reranker_applied: bool
            reranker_backend: str
            similarity_scores: list[float]
            top_k_requested: int
            similarity_threshold_used: float

    QueryResponse:
        Full response for a synchronous (non-streaming) query.
        Fields:
            answer: str             — the generated answer text
            citations: list[CitationSchema]
            session_id: str
            query_id: str           — UUID for request tracing
            confidence: float       — 0.0 to 1.0 heuristic score
            cache_hit: bool         — True if served from ResponseCache
            retrieval_metadata: RetrievalMetadataSchema
            pipeline_metadata: PipelineMetadataSchema

    StreamingChunkSchema:
        A single SSE event payload.
        Fields:
            event: str      — "token" | "citation" | "done" | "error"
            data: str       — JSON payload string for the event
            query_id: str

Validation Rules:
    - question: min_length=1, max_length=2000
    - session_id: must be a valid UUID4 string
    - top_k: ge=3, le=10 (when provided)
    - document_ids: each element must be a valid UUID4 string

Dependencies:
    - pydantic (BaseModel, Field, field_validator)
    - uuid
"""
