"""Session management endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from app.cache.response_cache import ResponseCache
from app.db.session_store import SessionStore
from app.dependencies import get_current_user, get_response_cache, get_session_store
from app.exceptions import SessionNotFoundError
from app.models.user import User
from app.schemas.session import (
    ConversationTurnSchema,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionDeleteResponse,
    SessionDetailResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse, status_code=201)
async def create_session(
    body: SessionCreateRequest,
    store: SessionStore = Depends(get_session_store),
    current_user: User = Depends(get_current_user),
):
    session = await store.create_session(body.document_ids or [])
    expires_at = store.expires_at(session)
    return SessionCreateResponse(
        session_id=session.session_id,
        document_ids=session.document_ids,
        created_at=session.created_at,
        expires_at=expires_at,
        message="Session created successfully.",
    )


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
    current_user: User = Depends(get_current_user),
):
    session = await store.get_session(session_id)
    if session is None:
        raise SessionNotFoundError(f"Session {session_id} not found or expired.")
    expires_at = store.expires_at(session)
    history = [
        ConversationTurnSchema(
            turn_index=i,
            user_query=t.user_query,
            standalone_query=t.standalone_query,
            assistant_response=t.assistant_response,
            citations=[],
            timestamp=t.timestamp,
        )
        for i, t in enumerate(session.conversation_history)
    ]
    return SessionDetailResponse(
        session_id=session.session_id,
        document_ids=session.document_ids,
        conversation_history=history,
        turn_count=session.turn_count,
        created_at=session.created_at,
        last_active_at=session.last_active_at,
        expires_at=expires_at,
    )


@router.delete("/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
    response_cache: ResponseCache = Depends(get_response_cache),
    current_user: User = Depends(get_current_user),
):
    turns_cleared = await store.delete_session(session_id)
    if turns_cleared is None:
        raise SessionNotFoundError(f"Session {session_id} not found.")
    await response_cache.invalidate_session(session_id)
    return SessionDeleteResponse(
        session_id=session_id,
        message="Session deleted successfully.",
        turns_cleared=turns_cleared,
    )
