# DocMind

A production-grade AI-powered PDF Q&A system with conversational memory, source citations, and token-streaming responses. Upload any PDF and chat with it in real time.

Every answer is grounded exclusively in uploaded PDF content — no hallucinations from the LLM's prior knowledge.

**Live demo:** Deploy your own on [Railway](https://railway.app) using the included `Dockerfile` and `railway.json`.

---

## Features

- **Web UI** — ChatGPT-style interface with sidebar showing previous chats, session switching, and persistent history
- **JWT authentication** — register/login UI overlay; all API endpoints protected with Bearer tokens
- **Streaming responses** — tokens arrive in real time with a typing effect (SSE)
- **Conversational memory** — multi-turn follow-up questions resolved automatically
- **Inference query support** — vague questions like "Is he a bad guy?" are expanded into semantic search terms before retrieval
- **Source citations** — every answer cites the exact PDF pages used
- **Persistent storage** — ChromaDB default with built-in disk persistence; sessions and document registry survive server restarts
- **PDF OCR fallback** — scanned PDFs automatically processed with Tesseract when text extraction yields no content
- **Optional reranking** — cross-encoder or Cohere reranker for higher precision

---

## Architecture

```
Auth Layer (JWT)
  │  POST /auth/register  POST /auth/login  GET /auth/me
  │  UserStore (SQLite)   ←→   bcrypt + python-jose
  │
API Layer  (all endpoints require Authorization: Bearer <token>)
  │
  ├── POST /documents/upload  ──►  IngestionPipeline
  │                                   parse → clean → chunk → embed → store
  │                                   (OCR fallback for scanned PDFs)
  │
  └── POST /query             ──►  RAGPipeline  ◄── central orchestrator
       POST /query/stream             │
                                      ├── ResponseCache (check/store)
                                      ├── QueryReformulator  ← always runs
                                      ├── EmbeddingCache (embed query)
                                      ├── RetrieverService (search + MMR)
                                      ├── RerankerService (cross-encoder, optional)
                                      ├── MemoryManager (read history)
                                      ├── RAGChain (prompt + LLM + citations)
                                      └── MemoryManager (write turn)
```

### Layer Responsibilities

| Layer | Location | Purpose |
|---|---|---|
| **Auth** | `app/auth/`, `app/db/user_store.py` | JWT issuance, password hashing, SQLite user store. |
| **Pipeline** | `app/pipeline/` | End-to-end orchestration. The only layer API handlers call. |
| **Chains** | `app/chains/` | LLM-only: prompt assembly, OpenAI call, citation extraction. |
| **Services** | `app/services/` | Single-responsibility units (parse, chunk, embed, retrieve, rerank). |
| **Cache** | `app/cache/` | Embedding cache (24h) and response cache (60s). |
| **Memory** | `app/memory/` | History formatting, token budgeting, compression. |
| **DB** | `app/db/` | VectorStore (ChromaDB/FAISS), SessionStore, DocumentRegistry, UserStore. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI (async) |
| LLM + Embeddings | OpenAI (`gpt-4o`, `text-embedding-3-small`) |
| Vector DB | ChromaDB (default, persistent) / FAISS |
| PDF parsing | PyMuPDF → pdfplumber → Tesseract OCR (3-level fallback) |
| Authentication | python-jose (JWT) + bcrypt + aiosqlite |
| Tokenization | tiktoken |
| Reranker (optional) | Cohere Rerank API or local cross-encoder |
| Frontend | Vanilla JS + CSS (served as static files) |
| Containerization | Docker + Railway |

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/garg-kavya/rag-pdf-qa
cd rag-pdf-qa
cp .env.example .env
# Edit .env and set OPENAI_API_KEY=sk-...
```

### 2. Run with Docker

```bash
docker-compose up --build
```

### 3. Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **`http://localhost:8000`** to use the web UI.
API docs: `http://localhost:8000/docs`

---

## Deployment (Railway)

1. Push this repo to GitHub
2. Create a new Railway project → "Deploy from GitHub repo"
3. Add `OPENAI_API_KEY` in Railway's environment variables
4. Railway auto-detects `Dockerfile` and `railway.json`; deploys on every push

The app reads `PORT` from Railway's environment automatically.

---

## API

| Method | Endpoint | Auth required | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | No | Register a new user account |
| `POST` | `/api/v1/auth/login` | No | Login; returns JWT access token |
| `GET` | `/api/v1/auth/me` | Yes | Get current user info |
| `POST` | `/api/v1/documents/upload` | Yes | Upload and ingest a PDF (async) |
| `GET` | `/api/v1/documents/{id}` | Yes | Check processing status |
| `DELETE` | `/api/v1/documents/{id}` | Yes | Remove document and its vectors |
| `POST` | `/api/v1/sessions` | Yes | Create a conversation session |
| `GET` | `/api/v1/sessions/{id}` | Yes | Get session + conversation history |
| `DELETE` | `/api/v1/sessions/{id}` | Yes | End a session |
| `POST` | `/api/v1/query` | Yes | Ask a question (full response) |
| `POST` | `/api/v1/query/stream` | Yes | Ask a question (SSE streaming) |
| `GET` | `/api/v1/health` | No | Service health + stats |
| `GET` | `/api/v1/debug/index` | No | Vector index stats + stored doc IDs |
| `GET` | `/api/v1/debug/search?q=...` | No | Raw similarity scores for a query |

Full contracts: [`docs/api_contracts.md`](docs/api_contracts.md)

---

## Usage Example

```bash
# 0. Register and login
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "secret"}'

TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'username=you@example.com&password=secret' | jq -r .access_token)

# 1. Upload a PDF
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@report.pdf"
# → {"document_id": "a1b2...", "status": "processing"}

# 2. Create a session
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"document_ids": ["a1b2..."]}'
# → {"session_id": "c3d4...", "expires_at": "..."}

# 3. Ask a question
curl -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What were the key risks?", "session_id": "c3d4..."}'
```

```json
{
  "answer": "Three key risks were identified: supply chain disruptions [Source 1], regulatory costs [Source 2], and cybersecurity threats [Source 3].",
  "citations": [
    {"document_name": "report.pdf", "page_numbers": [32], "chunk_index": 67, "excerpt": "Supply chain disruptions..."}
  ],
  "query_id": "q-abc-123",
  "confidence": 0.87,
  "cache_hit": false,
  "pipeline_metadata": {
    "total_time_ms": 1243,
    "retrieval_time_ms": 67,
    "reranking_time_ms": 0,
    "generation_time_ms": 982,
    "embedding_cache_hit": false,
    "reranker_backend": "none"
  }
}
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `LLM_MODEL` | `gpt-4o` | Generation model |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `CHUNK_SIZE_TOKENS` | `512` | Tokens per chunk |
| `CHUNK_OVERLAP_TOKENS` | `64` | Overlap between chunks |
| `VECTOR_STORE_TYPE` | `chroma` | `chroma` (default) or `faiss` |
| `TOP_K` | `10` | Final chunks passed to LLM |
| `TOP_K_CANDIDATES` | `20` | Candidates fetched before reranking |
| `SIMILARITY_THRESHOLD` | `0.0` | Min relevance score (0.0 = disabled) |
| `RERANKER_BACKEND` | `none` | `none`, `cross_encoder`, or `cohere` |
| `COHERE_API_KEY` | — | Required if `RERANKER_BACKEND=cohere` |
| `JWT_SECRET_KEY` | *(change in prod)* | Secret for signing JWT tokens |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` | Token TTL (default: 7 days) |
| `EMBEDDING_CACHE_TTL_SECONDS` | `86400` | 24h embedding cache |
| `RESPONSE_CACHE_TTL_SECONDS` | `60` | 60s response cache |
| `MEMORY_TOKEN_BUDGET` | `1024` | Max tokens for conversation history |
| `SESSION_TTL_MINUTES` | `60` | Session inactivity expiry |

Full reference: [`.env.example`](.env.example)

> **Note on `SIMILARITY_THRESHOLD`:** `text-embedding-3-small` cosine similarity scores for semantically related (but not near-identical) text typically fall in the 0.10–0.29 range. The default of `0.0` disables threshold filtering so all retrieved chunks are passed to MMR. Raise this only if you are seeing irrelevant chunks in answers.

---

## Performance

| Metric | Target | How achieved |
|---|---|---|
| Time to first token | <1.2s | Pre-computed doc embeddings + SSE streaming |
| Median query latency | <2s | FAISS in-memory + embedding cache + streaming |
| Precision@5 (no reranker) | ~0.65–0.75 | 512-token chunks + MMR |
| Precision@5 (with reranker) | ~0.75–0.88 | Cross-encoder reranking + MMR |

Latency breakdown (no reranker):
```
Session lookup       <1ms
Response cache check <1ms
Reformulation       50–300ms  (runs on every turn)
Embedding           1–150ms   (near-zero on cache hit)
Vector search       10–100ms  (ChromaDB default)
MMR selection       5–20ms
LLM first token     300–500ms
─────────────────────────────
Total to first token ~750–1100ms
```

---

## Tests

```bash
pytest                              # all tests
pytest tests/test_rag_pipeline.py   # pipeline integration
pytest -m "not integration"         # skip tests requiring OpenAI
pytest --cov=app                    # with coverage
```

---

## Benchmarking

```bash
python scripts/benchmark.py --queries 50 --concurrent 10
python scripts/seed_test_data.py
```

---

## Documentation

| Document | Description |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Layer model, component reference, design decisions |
| [`docs/data_flow.md`](docs/data_flow.md) | Step-by-step ingestion and query pipeline traces |
| [`docs/retrieval_strategy.md`](docs/retrieval_strategy.md) | Chunk size analysis, reranking, top-k tuning, P@5 |
| [`docs/api_contracts.md`](docs/api_contracts.md) | Full JSON request/response for all endpoints |

---

## Project Structure

```
app/
├── api/             FastAPI endpoints (thin: validate → delegate → map)
│   ├── v1/          documents, query, sessions, health, debug, auth
│   └── middleware/  rate limiter, error handler
├── auth/            JWT token creation/validation, password hashing
├── frontend/        Web UI (HTML + CSS + JS, served as static files)
│                    Includes register/login overlay; auth token in localStorage
├── pipeline/        ◄── orchestration layer
│   ├── rag_pipeline.py       query orchestrator
│   └── ingestion_pipeline.py PDF ingestion orchestrator
├── chains/          LLM-only: prompt assembly, OpenAI call, citation parse
├── services/        Single-responsibility services
│   ├── pdf_processor  PyMuPDF → pdfplumber → Tesseract OCR (3-level fallback)
│   ├── text_cleaner, chunker, embedder
│   ├── retriever, reranker, query_reformulator, streaming
├── cache/           Embedding cache + response cache + backend abstraction
├── memory/          MemoryManager, ContextBuilder, MemoryCompressor
├── db/              VectorStore (ChromaDB/FAISS), SessionStore, DocumentRegistry
│                    UserStore (SQLite via aiosqlite)
├── models/          Domain models (QueryContext, ScoredChunk, GeneratedAnswer, User...)
├── schemas/         Pydantic API schemas + typed metadata schemas
├── utils/           file_utils, token_counter, logging
├── exceptions.py    Centralized exception hierarchy
├── config.py        All settings (app, OpenAI, chunking, retrieval,
│                      reranker, cache, memory, session, JWT, server)
├── dependencies.py  DI wiring + startup order
└── main.py          FastAPI app + lifespan

data/                ChromaDB persistent store, session store, document registry,
│                    users SQLite DB
uploads/             Uploaded PDF files
tests/               Unit + integration stubs for all modules
docs/                Architecture, data flow, retrieval strategy, API contracts
scripts/             benchmark.py, seed_test_data.py
Dockerfile           Multi-stage Docker build (includes tesseract-ocr + poppler-utils)
docker-compose.yml   Local development with volume mounts
railway.json         Railway deployment configuration
requirements.txt     Pinned production dependencies
```

---

## License

MIT
