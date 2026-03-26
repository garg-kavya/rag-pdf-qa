"""ChromaDB vector store implementation."""
from __future__ import annotations

import json

from app.db.vector_store import VectorStore
from app.exceptions import StorageReadError, StorageWriteError
from app.models.chunk import Chunk
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ChromaStore(VectorStore):
    """ChromaDB persistent vector store with native metadata filtering."""

    def __init__(self, persist_path: str = "./data/chroma", collection_name: str = "pdf_chunks") -> None:
        import chromadb
        self._client = chromadb.PersistentClient(path=persist_path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def add_chunks(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        ids, embeddings, documents, metadatas = [], [], [], []
        for chunk in chunks:
            if chunk.embedding is None:
                raise StorageWriteError(f"Chunk {chunk.chunk_id} has no embedding.")
            ids.append(chunk.chunk_id)
            embeddings.append(chunk.embedding)
            documents.append(chunk.text)
            metadatas.append({
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "document_name": chunk.document_name,
                "chunk_index": chunk.chunk_index,
                "page_numbers": json.dumps(chunk.page_numbers),
                "token_count": chunk.token_count,
            })
        try:
            self._collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
        except Exception as exc:
            raise StorageWriteError(f"ChromaDB add failed: {exc}") from exc

        logger.info("Added %d vectors to ChromaDB collection", len(chunks))

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        # Guard: ChromaDB raises if n_results > collection size
        count = self._collection.count()
        if count == 0:
            return []

        where = {"document_id": {"$in": document_ids}} if document_ids else None
        n_results = min(top_k, count)

        try:
            result = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise StorageReadError(f"ChromaDB search failed: {exc}") from exc

        chunks_scores: list[tuple[Chunk, float]] = []
        for doc_text, meta, dist in zip(
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        ):
            chunk = Chunk(
                chunk_id=meta.get("chunk_id", ""),
                document_id=meta["document_id"],
                document_name=meta["document_name"],
                chunk_index=meta["chunk_index"],
                text=doc_text,
                token_count=meta["token_count"],
                page_numbers=json.loads(meta["page_numbers"]),
                start_char_offset=0,
                end_char_offset=0,
            )
            # ChromaDB cosine distance → similarity (distance = 1 - similarity)
            score = 1.0 - dist
            chunks_scores.append((chunk, score))

        return chunks_scores

    async def delete_document(self, document_id: str) -> int:
        results = self._collection.get(where={"document_id": document_id})
        ids = results.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    async def get_collection_stats(self) -> dict:
        count = self._collection.count()
        # Count unique documents from metadata
        total_documents = 0
        if count > 0:
            all_meta = self._collection.get(include=["metadatas"])
            doc_ids = {m["document_id"] for m in all_meta.get("metadatas", []) if m}
            total_documents = len(doc_ids)
        return {
            "total_vectors": count,
            "total_documents": total_documents,
            "index_type": "ChromaDB",
            "dimensions": 1536,
        }
