"""SQLite-backed user store via aiosqlite."""
from __future__ import annotations

from datetime import datetime

import aiosqlite

from app.models.user import User
from app.utils.logging import get_logger

logger = get_logger(__name__)


class UserStore:

    def __init__(self, db_path: str = "./data/users.db") -> None:
        self._db_path = db_path

    async def create_table(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    hashed_password TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await db.commit()
        logger.info("User store ready at %s", self._db_path)

    async def create_user(self, email: str, hashed_password: str) -> User:
        user = User(email=email, hashed_password=hashed_password)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO users (user_id, email, hashed_password, created_at) VALUES (?, ?, ?, ?)",
                (user.user_id, user.email, user.hashed_password, user.created_at.isoformat()),
            )
            await db.commit()
        return user

    async def get_by_email(self, email: str) -> User | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT user_id, email, hashed_password, created_at FROM users WHERE email = ?",
                (email,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return User(
            user_id=row["user_id"],
            email=row["email"],
            hashed_password=row["hashed_password"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    async def get_by_id(self, user_id: str) -> User | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT user_id, email, hashed_password, created_at FROM users WHERE user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return User(
            user_id=row["user_id"],
            email=row["email"],
            hashed_password=row["hashed_password"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
