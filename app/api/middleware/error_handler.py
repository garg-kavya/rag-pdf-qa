"""
Global Error Handler Middleware
================================

Purpose:
    Catches unhandled exceptions and converts them into structured JSON
    error responses. Prevents stack traces from leaking to clients in
    production while providing useful error details in debug mode.

Error Categories and HTTP Status Codes:

    PDFParsingError         -> 422 Unprocessable Entity
    EmbeddingError          -> 502 Bad Gateway (upstream API failure)
    VectorStoreError        -> 500 Internal Server Error
    SessionNotFoundError    -> 404 Not Found
    SessionExpiredError     -> 410 Gone
    DocumentNotFoundError   -> 404 Not Found
    ValidationError         -> 400 Bad Request (Pydantic)
    RateLimitError          -> 429 Too Many Requests
    Exception (unhandled)   -> 500 Internal Server Error

Error Response Format:
    {
        "error": {
            "type": "PDFParsingError",
            "message": "Human-readable error description",
            "detail": "Additional context (debug mode only)",
            "request_id": "uuid-for-tracing"
        }
    }

Logging:
    - All errors are logged with full stack trace at ERROR level
    - 4xx errors include request context (path, method, client IP)
    - 5xx errors trigger alert-level logging

Dependencies:
    - fastapi (Request, Response)
    - fastapi.responses (JSONResponse)
    - app.exceptions (full exception hierarchy — single import resolves all types)
    - app.utils.logging (get_logger)
"""
