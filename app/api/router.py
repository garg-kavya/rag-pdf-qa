"""Central API router — registers all v1 endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, debug, documents, health, query, sessions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(sessions.router)
api_router.include_router(query.router)
api_router.include_router(health.router)
api_router.include_router(debug.router)
