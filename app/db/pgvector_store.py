"""pgvector-backed vector store — vectors live in PostgreSQL alongside user/auth data."""
from __future__ import annotations

import numpy as np
import asyncpg

from app.db.vector_store import VectorStore
from app.exceptions import StorageReadError, StorageWriteError
from app.models.chunk import Chunk
from app.utils.logging import get_logger

logger = get_logger(__name__)


class PGVectorStore(VectorStore):
    """Stores chunk embeddings in a PostgreSQL table using the pgvector extension.

    Because it shares the same PostgreSQL instance as user/auth data it
    survives Railway restarts with zero additional infrastructure.
    """

    def __init__(self, dimensions: int = 1536, pool: asyncpg.Pool | None = None) -> None:
        self._dimensions = dimensions
        self._pool = pool  # injected in main.py lifespan after pool creation

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the table, FTS column, and indexes. Safe to call on every startup."""
        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    chunk_id          TEXT PRIMARY KEY,
                    document_id       TEXT NOT NULL,
                    document_name     TEXT NOT NULL,
                    chunk_index       INTEGER NOT NULL,
                    text              TEXT NOT NULL,
                    token_count       INTEGER NOT NULL DEFAULT 0,
                    page_numbers      INTEGER[] NOT NULL DEFAULT '{{}}',
                    start_char_offset INTEGER NOT NULL DEFAULT 0,
                    end_char_offset   INTEGER NOT NULL DEFAULT 0,
                    embedding         vector({self._dimensions}) NOT NULL
                )
            """)
            # Full-text search column: 'simple' dictionary = no stemming, so serial
            # numbers like "ABX-9942" are preserved as exact tokens.
            await conn.execute("""
                ALTER TABLE document_chunks
                ADD COLUMN IF NOT EXISTS text_search tsvector
                GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS document_chunks_document_id_idx
                ON document_chunks (document_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS document_chunks_text_search_idx
                ON document_chunks USING GIN (text_search)
            """)
        logger.info("PGVectorStore ready (dim=%d, hybrid search enabled)", self._dimensions)

    # ------------------------------------------------------------------
    # VectorStore interface
    # ------------------------------------------------------------------

    async def add_chunks(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        rows = []
        for chunk in chunks:
            if chunk.embedding is None:
                raise StorageWriteError(f"Chunk {chunk.chunk_id} has no embedding.")
            rows.append((
                chunk.chunk_id,
                chunk.document_id,
                chunk.document_name,
                chunk.chunk_index,
                chunk.text,
                chunk.token_count,
                chunk.page_numbers,
                chunk.start_char_offset,
                chunk.end_char_offset,
                np.array(chunk.embedding, dtype=np.float32),
            ))
        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO document_chunks
                        (chunk_id, document_id, document_name, chunk_index, text,
                         token_count, page_numbers, start_char_offset, end_char_offset,
                         embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        text      = EXCLUDED.text
                    """,
                    rows,
                )
        except Exception as exc:
            raise StorageWriteError(f"pgvector insert failed: {exc}") from exc
        logger.info("Stored %d vectors in pgvector", len(chunks))

    async def search(
        self,
        query_embedding: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        q_vec = np.array(query_embedding, dtype=np.float32)
        try:
            async with self._pool.acquire() as conn:
                if document_ids:
                    rows = await conn.fetch(
                        """
                        SELECT chunk_id, document_id, document_name, chunk_index, text,
                               token_count, page_numbers, start_char_offset, end_char_offset,
                               1 - (embedding <=> $1) AS similarity
                        FROM document_chunks
                        WHERE document_id = ANY($2)
                        ORDER BY embedding <=> $1
                        LIMIT $3
                        """,
                        q_vec, document_ids, top_k,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT chunk_id, document_id, document_name, chunk_index, text,
                               token_count, page_numbers, start_char_offset, end_char_offset,
                               1 - (embedding <=> $1) AS similarity
                        FROM document_chunks
                        ORDER BY embedding <=> $1
                        LIMIT $2
                        """,
                        q_vec, top_k,
                    )
        except Exception as exc:
            raise StorageReadError(f"pgvector search failed: {exc}") from exc

        return [
            (
                Chunk(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    document_name=row["document_name"],
                    chunk_index=row["chunk_index"],
                    text=row["text"],
                    token_count=row["token_count"],
                    page_numbers=list(row["page_numbers"]),
                    start_char_offset=row["start_char_offset"],
                    end_char_offset=row["end_char_offset"],
                ),
                float(row["similarity"]),
            )
            for row in rows
        ]

    async def keyword_search(
        self,
        query: str,
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """BM25-style keyword search using PostgreSQL full-text search.

        Uses the 'simple' dictionary (no stemming) so exact tokens like
        serial numbers and model codes are matched verbatim.
        ts_rank_cd scores are normalized to [0, 1] before returning.
        """
        try:
            async with self._pool.acquire() as conn:
                if document_ids:
                    rows = await conn.fetch(
                        """
                        SELECT chunk_id, document_id, document_name, chunk_index, text,
                               token_count, page_numbers, start_char_offset, end_char_offset,
                               ts_rank_cd(text_search, plainto_tsquery('simple', $1)) AS kw_score
                        FROM document_chunks
                        WHERE text_search @@ plainto_tsquery('simple', $1)
                          AND document_id = ANY($2)
                        ORDER BY kw_score DESC
                        LIMIT $3
                        """,
                        query, document_ids, top_k,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT chunk_id, document_id, document_name, chunk_index, text,
                               token_count, page_numbers, start_char_offset, end_char_offset,
                               ts_rank_cd(text_search, plainto_tsquery('simple', $1)) AS kw_score
                        FROM document_chunks
                        WHERE text_search @@ plainto_tsquery('simple', $1)
                        ORDER BY kw_score DESC
                        LIMIT $2
                        """,
                        query, top_k,
                    )
        except Exception as exc:
            raise StorageReadError(f"pgvector keyword search failed: {exc}") from exc

        if not rows:
            return []

        # Normalize ts_rank_cd scores to [0, 1]
        max_score = max(float(row["kw_score"]) for row in rows) or 1.0
        return [
            (
                Chunk(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    document_name=row["document_name"],
                    chunk_index=row["chunk_index"],
                    text=row["text"],
                    token_count=row["token_count"],
                    page_numbers=list(row["page_numbers"]),
                    start_char_offset=row["start_char_offset"],
                    end_char_offset=row["end_char_offset"],
                ),
                float(row["kw_score"]) / max_score,
            )
            for row in rows
        ]

    async def delete_document(self, document_id: str) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM document_chunks WHERE document_id = $1", document_id
            )
        try:
            count = int(result.split()[-1])
        except (ValueError, IndexError):
            count = 0
        logger.info("Deleted %d vectors for document %s", count, document_id)
        return count

    async def get_collection_stats(self) -> dict:
        async with self._pool.acquire() as conn:
            total_vectors = await conn.fetchval("SELECT COUNT(*) FROM document_chunks") or 0
            total_documents = await conn.fetchval(
                "SELECT COUNT(DISTINCT document_id) FROM document_chunks"
            ) or 0
        return {
            "total_vectors": total_vectors,
            "total_documents": total_documents,
            "index_type": "pgvector/cosine",
            "dimensions": self._dimensions,
        }
