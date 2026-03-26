"""Abstract VectorStore interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.chunk import Chunk


class VectorStore(ABC):

    @abstractmethod
    async def add_chunks(self, chunks: list[Chunk]) -> None:
        """Store chunk vectors and metadata."""

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Return top_k (chunk, score) pairs by cosine similarity."""

    @abstractmethod
    async def delete_document(self, document_id: str) -> int:
        """Remove all vectors for a document. Return count removed."""

    @abstractmethod
    async def get_collection_stats(self) -> dict:
        """Return total_vectors, total_documents, index_type, dimensions."""

    async def save_to_disk(self) -> None:
        """Persist index to disk. No-op for backends with built-in persistence."""

    async def load_from_disk(self) -> None:
        """Load index from disk. No-op for backends with built-in persistence."""
