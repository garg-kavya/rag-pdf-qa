"""Global error handler middleware."""
from __future__ import annotations

import traceback
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from app.exceptions import (
    AppError,
    CacheError,
    ChunkingError,
    ContextTooLongError,
    DocumentNotFoundError,
    EmbeddingError,
    EmbeddingTimeoutError,
    FileTooLargeError,
    GenerationAPIError,
    GenerationTimeoutError,
    InvalidFileTypeError,
    NoDocumentsError,
    PDFParsingError,
    SessionExpiredError,
    SessionNotFoundError,
    StorageWriteError,
    TextExtractionError,
    ValidationError,
    VectorStoreError,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

_STATUS_MAP: dict[type, int] = {
    PDFParsingError: 422,
    TextExtractionError: 422,
    InvalidFileTypeError: 400,
    FileTooLargeError: 400,
    EmbeddingError: 502,
    EmbeddingTimeoutError: 504,
    GenerationAPIError: 502,
    GenerationTimeoutError: 504,
    ContextTooLongError: 422,
    ChunkingError: 422,
    VectorStoreError: 500,
    StorageWriteError: 500,
    SessionNotFoundError: 404,
    DocumentNotFoundError: 404,
    SessionExpiredError: 410,
    NoDocumentsError: 409,
    ValidationError: 400,
}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = str(uuid.uuid4())
    exc.request_id = request_id

    status = 500
    for exc_type, code in _STATUS_MAP.items():
        if isinstance(exc, exc_type):
            status = code
            break

    if status >= 500:
        logger.error(
            "Unhandled error %s: %s",
            type(exc).__name__, exc.message,
            extra={"request_id": request_id},
        )
    else:
        logger.warning(
            "%s: %s",
            type(exc).__name__, exc.message,
            extra={"request_id": request_id},
        )

    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "type": type(exc).__name__,
                "message": exc.message,
                "request_id": request_id,
            }
        },
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = str(uuid.uuid4())
    logger.error(
        "Unexpected error: %s\n%s",
        exc,
        traceback.format_exc(),
        extra={"request_id": request_id},
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "type": "InternalServerError",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            }
        },
    )
