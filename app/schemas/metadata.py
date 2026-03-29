"""Typed Pydantic metadata schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, computed_field


class PDFMetadata(BaseModel):
    title: str | None = None
    author: str | None = None
    creation_date: str | None = None
    producer: str | None = None
    page_count: int = 0
    file_size_bytes: int = 0
    parser_used: str = "pymupdf"


class ChunkMetadata(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    chunk_index: int
    page_numbers: list[int]
    token_count: int
    text: str


class RetrievalMetadata(BaseModel):
    retrieval_time_ms: float = 0.0
    candidates_considered: int = 0
    candidates_after_threshold: int = 0
    chunks_used: int = 0
    mmr_applied: bool = False
    reranker_applied: bool = False
    hybrid_search_applied: bool = False
    similarity_scores: list[float] = Field(default_factory=list)
    top_k_requested: int = 5
    similarity_threshold_used: float = 0.70


class SessionMetadata(BaseModel):
    session_id: str
    document_count: int
    turn_count: int
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime

    @computed_field  # type: ignore[misc]
    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


class IngestionMetadata(BaseModel):
    document_id: str
    filename: str
    page_count: int = 0
    total_chunks: int = 0
    total_tokens: int = 0
    parser_used: str = "pymupdf"
    ingestion_time_ms: float = 0.0
    embedding_model: str = "text-embedding-3-small"
