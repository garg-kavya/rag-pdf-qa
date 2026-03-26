"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.middleware.error_handler import app_error_handler, generic_error_handler
from app.api.middleware.rate_limiter import RateLimiterMiddleware
from app.api.router import api_router
from app.config import get_settings
from app.dependencies import build_app_state
from app.exceptions import AppError
from app.utils.file_utils import ensure_directory
from app.utils.logging import get_logger, setup_logging

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)

    # Ensure directories exist
    ensure_directory(settings.upload_dir)
    ensure_directory(settings.vector_store_path)

    # Build and attach object graph
    state = build_app_state(settings)
    for key, value in state.items():
        setattr(app.state, key, value)

    # Restore persisted state: vectors, document registry, sessions, users
    await app.state.vector_store.load_from_disk()
    await app.state.document_registry.load_from_disk()
    await app.state.session_store.load_from_disk()
    await app.state.user_store.create_table()
    logger.info("DocMind service started")

    # Background: periodic session cleanup
    async def _cleanup_loop():
        store = app.state.session_store
        while True:
            await asyncio.sleep(settings.session_cleanup_interval_seconds)
            removed = await store.cleanup_expired()
            if removed:
                logger.info("Cleaned up %d expired sessions", removed)

    cleanup_task = asyncio.create_task(_cleanup_loop())

    yield  # app is running

    cleanup_task.cancel()
    logger.info("DocMind service shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="DocMind — AI-powered PDF Q&A with conversational memory",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    app.add_middleware(RateLimiterMiddleware)

    # Error handlers
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_error_handler)

    # Serve frontend: root route first, then static assets, then API
    if os.path.isdir(_FRONTEND_DIR):
        @app.get("/", include_in_schema=False)
        async def serve_index() -> FileResponse:
            return FileResponse(os.path.join(_FRONTEND_DIR, "index.html"))

    # API routes
    app.include_router(api_router)

    # Static files LAST so /static/* never shadows API routes
    if os.path.isdir(_FRONTEND_DIR):
        app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="frontend_static")

    return app


app = create_app()
