# API Contracts — DocMind

All endpoints are prefixed with `/api/v1`. All request/response bodies are JSON unless specified otherwise.

All endpoints except `/auth/register`, `/auth/login`, and `/health` require:
```
Authorization: Bearer <access_token>
```
A missing or invalid token returns `401 Unauthorized`.

---

## 0. Authentication

### `POST /api/v1/auth/register`

#### Request Body

```json
{
    "email": "user@example.com",
    "password": "mysecretpassword"
}
```

#### Response — `201 Created`

```json
{
    "user_id": "e5f6a7b8-c9d0-1234-abcd-567890123456",
    "email": "user@example.com",
    "created_at": "2026-03-26T10:00:00Z"
}
```

#### Error Response

**409 Conflict — Email already registered:**
```json
{
    "error": {
        "type": "ValidationError",
        "message": "Email already registered.",
        "request_id": "req-abc-100"
    }
}
```

---

### `POST /api/v1/auth/login`

**Content-Type:** `application/x-www-form-urlencoded` (OAuth2 password flow)

#### Request Fields

| Field | Type | Description |
|---|---|---|
| `username` | string | User's email address |
| `password` | string | User's password |

#### Response — `200 OK`

```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer"
}
```

#### Error Response

**401 Unauthorized — Invalid credentials:**
```json
{
    "error": {
        "type": "ValidationError",
        "message": "Invalid email or password.",
        "request_id": "req-abc-101"
    }
}
```

---

### `GET /api/v1/auth/me`

Requires `Authorization: Bearer <token>`.

#### Response — `200 OK`

```json
{
    "user_id": "e5f6a7b8-c9d0-1234-abcd-567890123456",
    "email": "user@example.com",
    "created_at": "2026-03-26T10:00:00Z"
}
```

---

## 1. PDF Upload

### `POST /api/v1/documents/upload`

**Content-Type:** `multipart/form-data`

#### Request

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | File (binary) | Yes | The PDF file to upload |
| `session_id` | string (UUID) | No | Auto-associate with an existing session |

#### Response — `202 Accepted`

```json
{
    "document_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "filename": "annual_report_2024.pdf",
    "file_size_bytes": 2458901,
    "page_count": 47,
    "total_chunks": 0,
    "status": "processing",
    "message": "Document uploaded successfully. Processing in progress.",
    "created_at": "2026-03-26T10:30:00Z"
}
```

> **Note:** `total_chunks` is 0 initially; it populates when status becomes `"ready"`.
> Poll `GET /api/v1/documents/{document_id}` for updated status.

#### Error Responses

**400 Bad Request — Invalid file type:**
```json
{
    "error": {
        "type": "ValidationError",
        "message": "Only PDF files are accepted. Received: image/jpeg",
        "detail": null,
        "request_id": "req-abc-123"
    }
}
```

**400 Bad Request — File too large:**
```json
{
    "error": {
        "type": "ValidationError",
        "message": "File size 67.2MB exceeds maximum allowed 50MB.",
        "detail": null,
        "request_id": "req-abc-124"
    }
}
```

---

## 2. Document Status

### `GET /api/v1/documents/{document_id}`

#### Response — `200 OK`

```json
{
    "document_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "filename": "annual_report_2024.pdf",
    "status": "ready",
    "page_count": 47,
    "total_chunks": 92,
    "metadata": {
        "title": "Acme Corp Annual Report 2024",
        "author": "Finance Department",
        "creation_date": "2024-12-15",
        "producer": "Microsoft Word"
    },
    "created_at": "2026-03-26T10:30:00Z",
    "processed_at": "2026-03-26T10:30:14Z",
    "error_message": null
}
```

#### Status Values

| Status | Meaning |
|---|---|
| `"uploaded"` | File received, not yet processing |
| `"processing"` | Parsing, chunking, and embedding in progress |
| `"ready"` | Fully indexed and queryable |
| `"error"` | Processing failed; see `error_message` |

#### Error Response

**404 Not Found:**
```json
{
    "error": {
        "type": "DocumentNotFoundError",
        "message": "Document a1b2c3d4-e5f6-7890-abcd-ef1234567890 not found.",
        "detail": null,
        "request_id": "req-abc-125"
    }
}
```

---

## 3. Delete Document

### `DELETE /api/v1/documents/{document_id}`

#### Response — `200 OK`

```json
{
    "document_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "message": "Document and 92 associated chunks have been removed.",
    "chunks_removed": 92
}
```

---

## 4. List Documents

### `GET /api/v1/documents`

#### Query Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `status` | string | all | Filter by status |
| `limit` | int | 50 | Max results |
| `offset` | int | 0 | Pagination offset |

#### Response — `200 OK`

```json
{
    "documents": [
        {
            "document_id": "a1b2c3d4-...",
            "filename": "annual_report_2024.pdf",
            "status": "ready",
            "page_count": 47,
            "total_chunks": 92,
            "created_at": "2026-03-26T10:30:00Z"
        },
        {
            "document_id": "b2c3d4e5-...",
            "filename": "q3_financials.pdf",
            "status": "processing",
            "page_count": 12,
            "total_chunks": 0,
            "created_at": "2026-03-26T10:35:00Z"
        }
    ],
    "total_count": 2
}
```

---

## 5. Create Session

### `POST /api/v1/sessions`

#### Request Body

```json
{
    "document_ids": [
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    ],
    "config_overrides": {
        "top_k": 7,
        "similarity_threshold": 0.75
    }
}
```

> Both fields are optional. `document_ids` can be `null` or omitted (add documents later). `config_overrides` can be `null` or omitted (use defaults).

#### Response — `201 Created`

```json
{
    "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
    "document_ids": [
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    ],
    "created_at": "2026-03-26T10:40:00Z",
    "expires_at": "2026-03-26T11:40:00Z",
    "message": "Session created successfully."
}
```

---

## 6. Get Session Details

### `GET /api/v1/sessions/{session_id}`

#### Response — `200 OK`

```json
{
    "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
    "document_ids": [
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    ],
    "conversation_history": [
        {
            "turn_index": 0,
            "user_query": "What was Acme Corp's Q3 2024 revenue?",
            "standalone_query": "What was Acme Corp's Q3 2024 revenue?",
            "assistant_response": "According to the annual report, Acme Corp's Q3 2024 revenue was $4.2 million [Source 1], representing a 15% increase year-over-year [Source 2].",
            "citations": [
                {
                    "document_name": "annual_report_2024.pdf",
                    "page_numbers": [5],
                    "chunk_index": 12,
                    "chunk_id": "d4e5f6a7-b8c9-0123-defg-234567890123",
                    "excerpt": "Q3 2024 revenue reached $4.2 million..."
                },
                {
                    "document_name": "annual_report_2024.pdf",
                    "page_numbers": [5, 6],
                    "chunk_index": 13,
                    "chunk_id": "e5f6a7b8-c9d0-1234-efgh-345678901234",
                    "excerpt": "...representing a 15% increase compared to Q3 2023..."
                }
            ],
            "timestamp": "2026-03-26T10:42:00Z"
        },
        {
            "turn_index": 1,
            "user_query": "How does that compare to Q2?",
            "standalone_query": "How does Acme Corp's Q3 2024 revenue of $4.2 million compare to Q2 2024 revenue?",
            "assistant_response": "Q2 2024 revenue was $3.8 million [Source 1], making Q3's $4.2 million an increase of approximately 10.5% quarter-over-quarter [Source 2].",
            "citations": [
                {
                    "document_name": "annual_report_2024.pdf",
                    "page_numbers": [4],
                    "chunk_index": 9,
                    "chunk_id": "f6a7b8c9-d0e1-2345-fghi-456789012345",
                    "excerpt": "Q2 2024 revenue totaled $3.8 million..."
                },
                {
                    "document_name": "annual_report_2024.pdf",
                    "page_numbers": [7],
                    "chunk_index": 18,
                    "chunk_id": "a7b8c9d0-e1f2-3456-ghij-567890123456",
                    "excerpt": "Quarter-over-quarter growth accelerated in the second half..."
                }
            ],
            "timestamp": "2026-03-26T10:42:30Z"
        }
    ],
    "turn_count": 2,
    "created_at": "2026-03-26T10:40:00Z",
    "last_active_at": "2026-03-26T10:42:30Z",
    "expires_at": "2026-03-26T11:42:30Z"
}
```

---

## 7. Delete Session

### `DELETE /api/v1/sessions/{session_id}`

#### Response — `200 OK`

```json
{
    "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
    "message": "Session deleted successfully.",
    "turns_cleared": 2
}
```

---

## 8. Query (Synchronous)

### `POST /api/v1/query`

#### Request Body

```json
{
    "question": "What were the key risk factors mentioned in the report?",
    "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
    "document_ids": ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    "top_k": 5,
    "stream": false
}
```

| Field | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `question` | string | Yes | — | 1-2000 characters |
| `session_id` | string (UUID) | Yes | — | Must exist and not be expired |
| `document_ids` | list[string] | No | all session docs | Valid UUIDs |
| `top_k` | int | No | 5 | 3-10 |
| `stream` | bool | No | false | Must be false for this endpoint |

#### Response — `200 OK`

```json
{
    "answer": "The report identifies three key risk factors: (1) supply chain disruptions due to geopolitical tensions [Source 1], (2) increasing regulatory compliance costs in the EU market [Source 2], and (3) cybersecurity threats to the company's digital infrastructure [Source 3]. The board noted that mitigation strategies are in place for each [Source 4].",
    "citations": [
        {
            "document_name": "annual_report_2024.pdf",
            "page_numbers": [32],
            "chunk_index": 67,
            "chunk_id": "b8c9d0e1-f2a3-4567-hijk-678901234567",
            "excerpt": "Supply chain disruptions remain a primary concern, driven by ongoing geopolitical tensions in key manufacturing regions..."
        },
        {
            "document_name": "annual_report_2024.pdf",
            "page_numbers": [33],
            "chunk_index": 69,
            "chunk_id": "c9d0e1f2-a3b4-5678-ijkl-789012345678",
            "excerpt": "Regulatory compliance costs, particularly related to the EU's Digital Markets Act, are projected to increase by 20%..."
        },
        {
            "document_name": "annual_report_2024.pdf",
            "page_numbers": [34],
            "chunk_index": 71,
            "chunk_id": "d0e1f2a3-b4c5-6789-jklm-890123456789",
            "excerpt": "The company experienced a 40% increase in attempted cyber intrusions compared to the prior year..."
        },
        {
            "document_name": "annual_report_2024.pdf",
            "page_numbers": [35],
            "chunk_index": 73,
            "chunk_id": "e1f2a3b4-c5d6-7890-klmn-901234567890",
            "excerpt": "The board has approved dedicated mitigation strategies for each identified risk factor..."
        }
    ],
    "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
    "query_id": "q-f2a3b4c5-d6e7-8901-lmno-012345678901",
    "confidence": 0.87,
    "retrieval_metadata": {
        "retrieval_time_ms": 87.3,
        "chunks_considered": 10,
        "chunks_used": 5,
        "similarity_scores": [0.91, 0.88, 0.85, 0.82, 0.78]
    }
}
```

#### Error Responses

**400 Bad Request — Empty question:**
```json
{
    "error": {
        "type": "ValidationError",
        "message": "Question must be between 1 and 2000 characters.",
        "detail": null,
        "request_id": "req-abc-130"
    }
}
```

**404 Not Found — Session not found:**
```json
{
    "error": {
        "type": "SessionNotFoundError",
        "message": "Session c3d4e5f6-... not found or has expired.",
        "detail": null,
        "request_id": "req-abc-131"
    }
}
```

---

## 9. Query (Streaming)

### `POST /api/v1/query/stream`

#### Request Body

Same as `POST /api/v1/query` (the `stream` field is ignored).

#### Response — `200 OK`

**Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Query-Id: q-f2a3b4c5-d6e7-8901-lmno-012345678901
```

**SSE Event Stream:**

```
event: token
data: {"text": "The", "query_id": "q-f2a3b4c5-..."}

event: token
data: {"text": " report", "query_id": "q-f2a3b4c5-..."}

event: token
data: {"text": " identifies", "query_id": "q-f2a3b4c5-..."}

event: token
data: {"text": " three", "query_id": "q-f2a3b4c5-..."}

... (tokens continue) ...

event: token
data: {"text": ".", "query_id": "q-f2a3b4c5-..."}

event: citation
data: {"citations": [{"document_name": "annual_report_2024.pdf", "page_numbers": [32], "chunk_index": 67, "chunk_id": "b8c9d0e1-...", "excerpt": "Supply chain disruptions..."}], "query_id": "q-f2a3b4c5-..."}

event: done
data: {"query_id": "q-f2a3b4c5-...", "total_tokens": 89, "retrieval_time_ms": 87.3, "confidence": 0.87}
```

**Error event (if generation fails mid-stream):**
```
event: error
data: {"message": "Generation interrupted: OpenAI API timeout", "query_id": "q-f2a3b4c5-..."}
```

---

## 10. Health Check

### `GET /api/v1/health`

#### Response — `200 OK` (healthy)

```json
{
    "status": "healthy",
    "version": "0.1.0",
    "checks": {
        "vector_store": "ok",
        "openai_api": "ok",
        "upload_dir": "ok"
    },
    "uptime_seconds": 3642.7,
    "active_sessions": 3,
    "total_documents": 12,
    "total_vectors": 1847
}
```

#### Response — `503 Service Unavailable` (unhealthy)

```json
{
    "status": "unhealthy",
    "version": "0.1.0",
    "checks": {
        "vector_store": "ok",
        "openai_api": "error",
        "upload_dir": "ok"
    },
    "uptime_seconds": 3642.7,
    "active_sessions": 3,
    "total_documents": 12,
    "total_vectors": 1847
}
```

---

## 11. Debug — Index Stats

### `GET /api/v1/debug/index`

Returns vector index statistics and the list of documents currently stored. Useful for diagnosing ingestion issues.

#### Response — `200 OK`

```json
{
    "total_vectors": 184,
    "index_type": "ChromaDB",
    "documents_in_registry": 3,
    "document_ids_in_index": [
        "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "c3d4e5f6-a7b8-9012-cdef-123456789012"
    ]
}
```

---

## 12. Debug — Similarity Search

### `GET /api/v1/debug/search?q={query}&doc_id={doc_id}`

Embeds the query and returns raw cosine similarity scores for all matching chunks. Use this to diagnose why a query may not be retrieving expected content.

#### Query Parameters

| Param | Type | Required | Description |
|---|---|---|---|
| `q` | string | Yes | The search query |
| `doc_id` | string (UUID) | No | Filter to a specific document |

#### Response — `200 OK`

```json
{
    "query": "what is the revenue?",
    "candidates_considered": 10,
    "candidates_after_threshold": 8,
    "results": [
        {
            "chunk_id": "d4e5f6a7-b8c9-0123-defg-234567890123",
            "document_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "similarity_score": 0.24,
            "page_numbers": [5],
            "excerpt": "Q3 2024 revenue reached $4.2 million..."
        }
    ]
}
```

> **Note on similarity scores:** `text-embedding-3-small` cosine similarity for semantically related (but not near-identical) text typically falls in the 0.10–0.29 range. Scores above 0.30 indicate very strong lexical overlap. This is expected behaviour — not low quality retrieval.

---

## Common Error Response Format

All error responses follow this structure:

```json
{
    "error": {
        "type": "string",
        "message": "string",
        "detail": "string | null",
        "request_id": "string"
    }
}
```

| HTTP Status | Error Type | When |
|---|---|---|
| 400 | `ValidationError` | Invalid request parameters |
| 401 | `HTTPException` | Missing or invalid JWT token |
| 404 | `DocumentNotFoundError` | Document ID not found |
| 404 | `SessionNotFoundError` | Session ID not found or expired |
| 409 | `ValidationError` | Email already registered |
| 410 | `SessionExpiredError` | Session existed but TTL elapsed |
| 422 | `PDFParsingError` | PDF is corrupted, encrypted, or unreadable |
| 422 | `ChunkingError` | PDF produced no usable text chunks |
| 429 | `RateLimitError` | Too many requests |
| 500 | `InternalError` | Unexpected server error |
| 502 | `UpstreamError` | OpenAI API failure |
| 504 | `EmbeddingTimeoutError` / `GenerationTimeoutError` | Upstream timeout |
