"""Session API schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    document_ids: list[str] | None = None
    config_overrides: dict | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    document_ids: list[str]
    created_at: datetime
    expires_at: datetime | None = None
    message: str


class ConversationTurnSchema(BaseModel):
    turn_index: int
    user_query: str
    standalone_query: str
    assistant_response: str
    citations: list[dict] = []
    timestamp: datetime


class SessionDetailResponse(BaseModel):
    session_id: str
    document_ids: list[str]
    conversation_history: list[ConversationTurnSchema]
    turn_count: int
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime | None = None


class SessionDeleteResponse(BaseModel):
    session_id: str
    message: str
    turns_cleared: int
