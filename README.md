# RAG PDF Q&A

A production-grade Retrieval-Augmented Generation (RAG) system for answering questions over uploaded PDF documents with conversational memory and source citations.

---

## Features

- **PDF ingestion pipeline** — Upload PDFs and have them automatically parsed, cleaned, chunked, embedded, and indexed
- **Semantic search** — Cosine similarity search over document chunks with MMR re-ranking for diversity
- **Citation-grounded answers** — Every answer references the exact source document, page, and chunk
- **Multi-turn Q&A** — Conversational memory with follow-up question resolution per session
- **Streaming responses** — Token-by-token SSE streaming for low perceived latency
- **Dual PDF parsers** — PyMuPDF (primary) with pdfplumber fallback for complex layouts
- **Flexible vector storage** — FAISS (fast, in-memory) or ChromaDB (persistent, metadata-rich)

---

## Architecture

```
PDF Upload → Parse → Clean → Chunk (512 tokens) → Embed → Vector DB
                                                              ↓
User Query → Reformulate → Embed → Retrieve (MMR) → Generate → Stream
```

See [`docs/architecture.md`](docs/architecture.md) for the full system design.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI (async) |
| Orchestration | LangChain / LangGraph |
| LLM + Embeddings | OpenAI (gpt-4o, text-embedding-3-small) |
| Vector DB | FAISS (default) / ChromaDB |
| PDF parsing | PyMuPDF, pdfplumber |
| Tokenization | tiktoken |
| Containerization | Docker |

---

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url>
cd "RAG-PDF Q&A"
cp .env.example .env
# Edit .env and set OPENAI_API_KEY=sk-...
```

### 2. Run with Docker

```bash
docker-compose up --build
```

Service is available at `http://localhost:8000`.

### 3. Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

---

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/documents/upload` | Upload a PDF |
| `GET` | `/api/v1/documents/{id}` | Check processing status |
| `DELETE` | `/api/v1/documents/{id}` | Remove a document |
| `POST` | `/api/v1/sessions` | Create a conversation session |
| `GET` | `/api/v1/sessions/{id}` | Get session + conversation history |
| `DELETE` | `/api/v1/sessions/{id}` | End a session |
| `POST` | `/api/v1/query` | Ask a question (full response) |
| `POST` | `/api/v1/query/stream` | Ask a question (SSE streaming) |
| `GET` | `/api/v1/health` | Service health check |

Full request/response schemas: [`docs/api_contracts.md`](docs/api_contracts.md)

Interactive docs (when running): `http://localhost:8000/docs`

---

## Usage Example

### Upload a PDF

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@report.pdf"
```

```json
{
  "document_id": "a1b2c3d4-...",
  "status": "processing",
  "page_count": 47
}
```

### Create a session

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"document_ids": ["a1b2c3d4-..."]}'
```

```json
{
  "session_id": "c3d4e5f6-...",
  "expires_at": "2026-03-26T11:40:00Z"
}
```

### Ask a question

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What were the key risk factors?",
    "session_id": "c3d4e5f6-..."
  }'
```

```json
{
  "answer": "The report identifies three key risks: supply chain disruptions [Source 1], regulatory compliance costs [Source 2], and cybersecurity threats [Source 3].",
  "citations": [
    {
      "document_name": "report.pdf",
      "page_numbers": [32],
      "chunk_index": 67,
      "excerpt": "Supply chain disruptions remain a primary concern..."
    }
  ],
  "confidence": 0.87
}
```

### Streaming response

```bash
curl -X POST http://localhost:8000/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Summarize the financials", "session_id": "c3d4e5f6-..."}'
```

```
event: token
data: {"text": "Revenue"}

event: token
data: {"text": " grew"}

event: citation
data: {"citations": [...]}

event: done
data: {"total_tokens": 142}
```

---

## Configuration

All settings are driven by environment variables (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `LLM_MODEL` | `gpt-4o` | Generation model |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `CHUNK_SIZE_TOKENS` | `512` | Tokens per chunk |
| `CHUNK_OVERLAP_TOKENS` | `64` | Overlap between chunks |
| `VECTOR_STORE_TYPE` | `faiss` | `faiss` or `chroma` |
| `TOP_K` | `5` | Chunks retrieved per query |
| `SIMILARITY_THRESHOLD` | `0.70` | Minimum relevance score |
| `SESSION_TTL_MINUTES` | `60` | Session expiry time |
| `MAX_UPLOAD_SIZE_MB` | `50` | Max PDF file size |

---

## Performance

| Metric | Target | How achieved |
|---|---|---|
| Median query latency | < 2s | FAISS in-memory search + OpenAI streaming |
| Time to first token | < 1.2s | Pre-computed doc embeddings, streaming generation |
| Precision@5 | 0.70–0.85 | 512-token chunks + MMR re-ranking |

Latency breakdown per query:

```
Session lookup        <1ms    (in-memory)
Query reformulation   0-400ms (skipped on first turn)
Query embedding       100-150ms
Vector search         10-50ms (FAISS)
Threshold + MMR       5-20ms
LLM first token       300-500ms
──────────────────────────────
Total to first token  ~650-1200ms
```

---

## Running Tests

```bash
pytest                        # all tests
pytest tests/test_chunker.py  # single file
pytest -m "not integration"   # skip tests requiring OpenAI API
pytest --cov=app              # with coverage
```

---

## Benchmarking

```bash
# Measure latency and retrieval quality
python scripts/benchmark.py --queries 50 --concurrent 10

# Seed with test documents
python scripts/seed_test_data.py
```

---

## Documentation

| Document | Description |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | System design, component breakdown, data flow diagrams |
| [`docs/data_flow.md`](docs/data_flow.md) | Step-by-step ingestion and query pipeline traces |
| [`docs/retrieval_strategy.md`](docs/retrieval_strategy.md) | Chunk size analysis, top-k tuning, precision@5 rationale |
| [`docs/api_contracts.md`](docs/api_contracts.md) | Full JSON request/response schemas for all endpoints |

---

## Project Structure

```
.
├── app/
│   ├── api/              # FastAPI routes (documents, query, sessions, health)
│   │   └── middleware/   # Rate limiter, error handler
│   ├── chains/           # RAG orchestration chain + prompt templates
│   ├── db/               # FAISS & ChromaDB implementations + session store
│   ├── models/           # Domain models (Document, Chunk, Session, Query)
│   ├── schemas/          # Pydantic API schemas
│   ├── services/         # Pipeline services (parse, clean, chunk, embed, retrieve, generate)
│   └── utils/            # File I/O, token counter, logging
├── configs/              # default.yaml
├── docs/                 # Architecture and API documentation
├── scripts/              # Benchmarking and seed data scripts
├── tests/                # Unit and integration test stubs
├── uploads/              # Uploaded PDFs (gitignored)
├── data/                 # Vector store persistence (gitignored)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## License

MIT
