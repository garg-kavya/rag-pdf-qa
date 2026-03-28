"""PostgreSQL-backed JWT token blocklist for stateless logout."""
from __future__ import annotations

from datetime import datetime

import asyncpg

from app.utils.logging import get_logger

logger = get_logger(__name__)


class TokenBlocklist:

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_table(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS token_blocklist (
                    jti TEXT PRIMARY KEY,
                    expires_at TIMESTAMPTZ NOT NULL
                )
            """)
        logger.info("Token blocklist table ready (PostgreSQL)")

    async def block(self, jti: str, expires_at: datetime) -> None:
        """Add a JTI to the blocklist so the token can no longer be used."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO token_blocklist (jti, expires_at) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                jti, expires_at,
            )

    async def is_blocked(self, jti: str) -> bool:
        """Return True if this JTI has been revoked."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM token_blocklist WHERE jti = $1", jti
            )
        return row is not None

    async def cleanup_expired(self) -> int:
        """Delete blocklist entries whose tokens have already expired naturally."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM token_blocklist WHERE expires_at < $1", datetime.utcnow()
            )
        # asyncpg returns "DELETE N" as a status string
        try:
            count = int(result.split()[-1])
        except (ValueError, IndexError):
            count = 0
        if count:
            logger.info("Purged %d expired blocklist entries", count)
        return count
