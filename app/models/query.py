"""Query and response domain models."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.schemas.metadata import RetrievalMetadata


@dataclass
class Citation:
    document_name: str
    page_numbers: list[int]
    chunk_index: int
    chunk_id: str
    excerpt: str


@dataclass
class ScoredChunk:
    chunk: "Chunk"
    similarity_score: float
    bi_encoder_score: float
    rerank_score: float | None = None
    rank: int = 0


@dataclass
class RetrievedContext:
    chunks: list[ScoredChunk]
    retrieval_metadata: "RetrievalMetadata"


@dataclass
class QueryContext:
    raw_query: str
    session_id: str
    document_ids: list[str]
    standalone_query: str = ""
    query_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    query_embedding: list[float] | None = None
    formatted_history: str = ""
    reranker_applied: bool = False
    cache_hit: bool = False


@dataclass
class PipelineMetadata:
    query_id: str
    total_time_ms: float = 0.0
    reformulation_time_ms: float = 0.0
    embedding_time_ms: float = 0.0
    retrieval_time_ms: float = 0.0
    reranking_time_ms: float = 0.0
    mmr_time_ms: float = 0.0
    generation_time_ms: float = 0.0
    memory_read_time_ms: float = 0.0
    memory_write_time_ms: float = 0.0
    embedding_cache_hit: bool = False
    response_cache_hit: bool = False
    reranker_backend: str = "none"
    llm_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    route: str = "rag"  # "rag" | "calculator"


@dataclass
class GeneratedAnswer:
    answer_text: str
    citations: list[Citation]
    confidence: float
    query_id: str
    cache_hit: bool
    retrieval_context: RetrievedContext | None
    pipeline_metadata: PipelineMetadata


@dataclass
class StreamingChunk:
    event: str  # "token" | "citation" | "done" | "error"
    data: dict
