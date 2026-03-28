"""Session store with TTL expiry and JSON persistence."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta

from app.config import Settings
from app.exceptions import SessionNotFoundError
from app.models.session import ConversationTurn, Session
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SessionStore:

    def __init__(self, settings: Settings, persist_path: str | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        # None = never expire (session_ttl_minutes == 0 → ChatGPT-style persistence)
        self._ttl: timedelta | None = (
            timedelta(minutes=settings.session_ttl_minutes)
            if settings.session_ttl_minutes > 0 else None
        )
        self._max_turns = settings.max_conversation_turns
        self._persist_path = persist_path

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def create_session(self, document_ids: list[str]) -> Session:
        session = Session(document_ids=list(document_ids))
        async with self._lock:
            self._sessions[session.session_id] = session
        logger.info("Created session %s", session.session_id)
        await self.save_to_disk()
        return session

    async def get_session(self, session_id: str) -> Session | None:
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return None
        if self._ttl is not None and datetime.utcnow() - session.last_active_at > self._ttl:
            return None  # expired; caller raises SessionExpiredError
        return session

    async def update_session(self, session_id: str, turn: ConversationTurn) -> Session:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(f"Session {session_id} not found.")
            session.conversation_history.append(turn)
            if len(session.conversation_history) > self._max_turns:
                session.conversation_history.pop(0)
            session.last_active_at = datetime.utcnow()
        await self.save_to_disk()
        return session

    async def replace_history(self, session_id: str, history: list[ConversationTurn]) -> None:
        """Replace the full history (used by MemoryCompressor)."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.conversation_history = history
        await self.save_to_disk()

    async def add_document_to_session(self, session_id: str, document_id: str) -> Session | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session and document_id not in session.document_ids:
                session.document_ids.append(document_id)
        await self.save_to_disk()
        return session

    async def delete_session(self, session_id: str) -> int | None:
        """Delete a session and return its turn count, or None if not found."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return None
        await self.save_to_disk()
        return session.turn_count

    async def cleanup_expired(self) -> int:
        if self._ttl is None:
            return 0  # sessions never expire
        now = datetime.utcnow()
        async with self._lock:
            expired = [
                sid for sid, s in self._sessions.items()
                if now - s.last_active_at > self._ttl
            ]
            for sid in expired:
                del self._sessions[sid]
        if expired:
            await self.save_to_disk()
        return len(expired)

    def expires_at(self, session: Session) -> datetime | None:
        if self._ttl is None:
            return None
        return session.last_active_at + self._ttl

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def save_to_disk(self) -> None:
        if not self._persist_path:
            return
        os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
        async with self._lock:
            data = {sid: self._session_to_dict(s) for sid, s in self._sessions.items()}
        try:
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.warning("Failed to save sessions to disk: %s", exc)

    async def load_from_disk(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
            loaded = 0
            async with self._lock:
                for sid, d in data.items():
                    try:
                        session = self._dict_to_session(d)
                        # Skip sessions that are already expired (unless TTL is disabled)
                        if self._ttl is None or datetime.utcnow() - session.last_active_at <= self._ttl:
                            self._sessions[sid] = session
                            loaded += 1
                    except Exception:
                        pass  # skip corrupted entries
            logger.info("Loaded %d active sessions from disk", loaded)
        except Exception as exc:
            logger.warning("Failed to load sessions from disk: %s", exc)

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _session_to_dict(session: Session) -> dict:
        from app.models.query import Citation

        def citation_to_dict(c: "Citation") -> dict:
            return {
                "document_name": c.document_name,
                "page_numbers": c.page_numbers,
                "chunk_index": c.chunk_index,
                "chunk_id": c.chunk_id,
                "excerpt": c.excerpt,
            }

        def turn_to_dict(t: ConversationTurn) -> dict:
            return {
                "user_query": t.user_query,
                "standalone_query": t.standalone_query,
                "assistant_response": t.assistant_response,
                "retrieved_chunk_ids": t.retrieved_chunk_ids,
                "citations": [citation_to_dict(c) for c in t.citations],
                "timestamp": t.timestamp.isoformat(),
                "is_summary": t.is_summary,
                "summary_text": t.summary_text,
                "turns_covered": t.turns_covered,
            }

        return {
            "session_id": session.session_id,
            "document_ids": session.document_ids,
            "conversation_history": [turn_to_dict(t) for t in session.conversation_history],
            "created_at": session.created_at.isoformat(),
            "last_active_at": session.last_active_at.isoformat(),
        }

    @staticmethod
    def _dict_to_session(d: dict) -> Session:
        from app.models.query import Citation

        def dict_to_citation(c: dict) -> "Citation":
            return Citation(
                document_name=c["document_name"],
                page_numbers=c["page_numbers"],
                chunk_index=c["chunk_index"],
                chunk_id=c["chunk_id"],
                excerpt=c["excerpt"],
            )

        def dict_to_turn(t: dict) -> ConversationTurn:
            return ConversationTurn(
                user_query=t["user_query"],
                standalone_query=t["standalone_query"],
                assistant_response=t["assistant_response"],
                retrieved_chunk_ids=t["retrieved_chunk_ids"],
                citations=[dict_to_citation(c) for c in t.get("citations", [])],
                timestamp=datetime.fromisoformat(t["timestamp"]),
                is_summary=t.get("is_summary", False),
                summary_text=t.get("summary_text"),
                turns_covered=t.get("turns_covered", 0),
            )

        session = Session.__new__(Session)
        session.session_id = d["session_id"]
        session.document_ids = d["document_ids"]
        session.conversation_history = [dict_to_turn(t) for t in d.get("conversation_history", [])]
        session.created_at = datetime.fromisoformat(d["created_at"])
        session.last_active_at = datetime.fromisoformat(d["last_active_at"])
        session.config_overrides = None
        return session
