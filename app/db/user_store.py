"""PostgreSQL-backed user store via asyncpg connection pool."""
from __future__ import annotations

from datetime import datetime

import asyncpg

from app.models.user import User
from app.utils.logging import get_logger

logger = get_logger(__name__)


class UserStore:

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_table(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    hashed_password TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
        logger.info("User store ready (PostgreSQL)")

    async def create_user(self, email: str, hashed_password: str) -> User:
        user = User(email=email, hashed_password=hashed_password)
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (user_id, email, hashed_password, created_at) VALUES ($1, $2, $3, $4)",
                user.user_id, user.email, user.hashed_password, user.created_at,
            )
        return user

    async def get_by_email(self, email: str) -> User | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, email, hashed_password, created_at FROM users WHERE email = $1",
                email,
            )
        if row is None:
            return None
        return User(
            user_id=row["user_id"],
            email=row["email"],
            hashed_password=row["hashed_password"],
            created_at=row["created_at"],
        )

    async def get_by_id(self, user_id: str) -> User | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, email, hashed_password, created_at FROM users WHERE user_id = $1",
                user_id,
            )
        if row is None:
            return None
        return User(
            user_id=row["user_id"],
            email=row["email"],
            hashed_password=row["hashed_password"],
            created_at=row["created_at"],
        )
