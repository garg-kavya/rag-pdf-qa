"""
Query Endpoints
================

Purpose:
    Handles user questions against uploaded PDF documents. Supports both
    synchronous (full response) and streaming (SSE) modes.

    API handlers here are intentionally thin — all business logic is
    delegated to RAGPipeline. The handler's only jobs are:
        1. Validate the incoming request (Pydantic schema validation)
        2. Call the appropriate RAGPipeline method
        3. Map the result to an API response schema

    Calling convention:
        POST /query      → RAGPipeline.run()         → QueryResponse
        POST /query/stream → RAGPipeline.run_stream() → StreamingResponse (SSE)

Endpoints:

    POST /api/v1/query
        Ask a question; receive a complete answer with citations.

        Request Body (JSON):
            {
                "question": str,        # required, 1-2000 chars
                "session_id": str,      # required, valid UUID
                "document_ids": [str],  # optional, filter to specific docs
                "top_k": int,           # optional, 3-10, override retrieval count
                "stream": false         # must be false for this endpoint
            }

        Handler steps:
            1. Validate QueryRequest (Pydantic)
            2. Call RAGPipeline.run(question, session_id, document_ids, top_k)
            3. Map GeneratedAnswer → QueryResponse schema
            4. Return 200 OK

        Response: 200 OK
            {
                "answer": str,
                "citations": [
                    {
                        "document_name": str,
                        "page_numbers": [int],
                        "chunk_index": int,
                        "chunk_id": str,
                        "excerpt": str
                    }
                ],
                "session_id": str,
                "query_id": str,
                "confidence": float,
                "cache_hit": bool,
                "retrieval_metadata": {
                    "retrieval_time_ms": float,
                    "candidates_considered": int,
                    "candidates_after_threshold": int,
                    "chunks_used": int,
                    "mmr_applied": bool,
                    "reranker_applied": bool,
                    "reranker_backend": str,
                    "similarity_scores": [float],
                    "top_k_requested": int,
                    "similarity_threshold_used": float
                },
                "pipeline_metadata": {
                    "total_time_ms": float,
                    "reformulation_time_ms": float,
                    "embedding_time_ms": float,
                    "retrieval_time_ms": float,
                    "reranking_time_ms": float,
                    "generation_time_ms": float,
                    "embedding_cache_hit": bool,
                    "response_cache_hit": bool,
                    "llm_model": str
                }
            }

        Errors:
            400 — Invalid request (empty question, bad UUID, top_k out of range)
            404 — Session not found or expired
            409 — Session has no documents (NoDocumentsError)
            422 — Document not ready (still processing)
            502 — OpenAI API failure
            504 — OpenAI API timeout

    POST /api/v1/query/stream
        Ask a question; receive a streaming SSE response.

        Request Body: Same as POST /api/v1/query.

        Handler steps:
            1. Validate QueryRequest (Pydantic)
            2. Call RAGPipeline.run_stream(question, session_id, document_ids, top_k)
            3. Wrap async generator in StreamingHandler.create_stream_response()
            4. Return StreamingResponse (text/event-stream)

        Response: 200 OK
            Content-Type: text/event-stream
            Cache-Control: no-cache
            Connection: keep-alive
            X-Query-Id: {query_id}

            SSE Events (in order):
                event: token
                data: {"text": "...", "query_id": "..."}
                ... (one per generated token)

                event: citation
                data: {"citations": [...], "query_id": "..."}

                event: done
                data: {
                    "query_id": "...",
                    "total_tokens": int,
                    "retrieval_time_ms": float,
                    "reranker_applied": bool,
                    "confidence": float
                }

                event: error  (only on failure)
                data: {"message": "...", "query_id": "..."}

        Errors: Sent as SSE error events rather than HTTP error codes,
                because headers are already committed when streaming starts.

Dependencies:
    - fastapi (APIRouter, Depends, HTTPException)
    - fastapi.responses (StreamingResponse)
    - app.schemas.query (QueryRequest, QueryResponse)
    - app.dependencies (get_rag_pipeline)
    - app.pipeline.rag_pipeline (RAGPipeline)
    - app.services.streaming (StreamingHandler)
    - app.exceptions (SessionNotFoundError, NoDocumentsError, ...)
"""
