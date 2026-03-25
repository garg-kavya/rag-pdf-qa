# RAG PDF Q&A

A production-grade Retrieval-Augmented Generation system for answering questions over uploaded PDF documents with conversational memory, source citations, and token-streaming responses.

Every answer is grounded exclusively in uploaded PDF content.

---

## Architecture

```
API Layer
  │
  ├── POST /documents/upload  ──►  IngestionPipeline
  │                                   parse → clean → chunk → embed → store
  │
  └── POST /query             ──►  RAGPipeline  ◄── central orchestrator
       POST /query/stream             │
                                      ├── ResponseCache (check/store)
                                      ├── QueryReformulator
                                      ├── EmbeddingCache (embed query)
                                      ├── RetrieverService (search + threshold)
                                      ├── RerankerService (cross-encoder, optional)
                                      ├── RetrieverService.apply_mmr (diversity)
                                      ├── MemoryManager (read history)
                                      ├── RAGChain (prompt + LLM + citations)
                                      └── MemoryManager (write turn)
```

### Layer Responsibilities

| Layer | Location | Purpose |
|---|---|---|
| **Pipeline** | `app/pipeline/` | End-to-end orchestration. The only layer API handlers call. |
| **Chains** | `app/chains/` | LLM-only: prompt assembly, OpenAI call, citation extraction. |
| **Services** | `app/services/` | Single-responsibility units (parse, chunk, embed, retrieve, rerank). |
| **Cache** | `app/cache/` | Embedding cache (24h) and response cache (60s). |
| **Memory** | `app/memory/` | History formatting, token budgeting, compression. |
| **DB** | `app/db/` | VectorStore, SessionStore, DocumentRegistry. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI (async) |
| LLM orchestration | LangChain / LangGraph |
| LLM + Embeddings | OpenAI (`gpt-4o`, `text-embedding-3-small`) |
| Vector DB | FAISS (default) / ChromaDB |
| PDF parsing | PyMuPDF + pdfplumber (fallback) |
| Tokenization | tiktoken |
| Reranker (optional) | Cohere Rerank API or local cross-encoder |
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

### 3. Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Service: `http://localhost:8000` — Interactive docs: `http://localhost:8000/docs`

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/documents/upload` | Upload and ingest a PDF (async) |
| `GET` | `/api/v1/documents/{id}` | Check processing status |
| `DELETE` | `/api/v1/documents/{id}` | Remove document and its vectors |
| `POST` | `/api/v1/sessions` | Create a conversation session |
| `GET` | `/api/v1/sessions/{id}` | Get session + conversation history |
| `DELETE` | `/api/v1/sessions/{id}` | End a session |
| `POST` | `/api/v1/query` | Ask a question (full response) |
| `POST` | `/api/v1/query/stream` | Ask a question (SSE streaming) |
| `GET` | `/api/v1/health` | Service health + stats |

Full contracts: [`docs/api_contracts.md`](docs/api_contracts.md)

---

## Usage Example

```bash
# 1. Upload a PDF
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@report.pdf"
# → {"document_id": "a1b2...", "status": "processing"}

# 2. Create a session
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"document_ids": ["a1b2..."]}'
# → {"session_id": "c3d4...", "expires_at": "..."}

# 3. Ask a question
curl -X POST http://localhost:8000/api/v1/query \
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
| `VECTOR_STORE_TYPE` | `faiss` | `faiss` or `chroma` |
| `TOP_K` | `5` | Final chunks passed to LLM |
| `TOP_K_CANDIDATES` | `10` | Candidates fetched before reranking |
| `SIMILARITY_THRESHOLD` | `0.70` | Min relevance score |
| `RERANKER_BACKEND` | `none` | `none`, `cross_encoder`, or `cohere` |
| `COHERE_API_KEY` | — | Required if `RERANKER_BACKEND=cohere` |
| `EMBEDDING_CACHE_TTL_SECONDS` | `86400` | 24h embedding cache |
| `RESPONSE_CACHE_TTL_SECONDS` | `60` | 60s response cache |
| `MEMORY_TOKEN_BUDGET` | `1024` | Max tokens for conversation history |
| `SESSION_TTL_MINUTES` | `60` | Session inactivity expiry |

Full reference: [`.env.example`](.env.example) and [`configs/default.yaml`](configs/default.yaml)

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
Reformulation       0–300ms  (skipped on first turn)
Embedding           1–150ms  (near-zero on cache hit)
Vector search       10–50ms
MMR selection       5–20ms
LLM first token     300–500ms
─────────────────────────────
Total to first token ~650–1000ms
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
│   ├── v1/          documents, query, sessions, health
│   └── middleware/  rate limiter, error handler
├── pipeline/        ◄── orchestration layer (new)
│   ├── rag_pipeline.py       query orchestrator
│   └── ingestion_pipeline.py PDF ingestion orchestrator
├── chains/          LLM-only: prompt assembly, OpenAI call, citation parse
├── services/        Single-responsibility services
│   ├── pdf_processor, text_cleaner, chunker, embedder
│   ├── retriever, reranker, query_reformulator, streaming
├── cache/           Embedding cache + response cache + backend abstraction
├── memory/          MemoryManager, ContextBuilder, MemoryCompressor
├── db/              VectorStore (FAISS/Chroma), SessionStore, DocumentRegistry
├── models/          Domain models (QueryContext, ScoredChunk, GeneratedAnswer...)
├── schemas/         Pydantic API schemas + typed metadata schemas
├── utils/           file_utils, token_counter, logging
├── exceptions.py    Centralized exception hierarchy
├── config.py        All settings (app, OpenAI, chunking, retrieval,
│                      reranker, cache, memory, session, server)
├── dependencies.py  DI wiring + startup order
└── main.py          FastAPI app + lifespan

tests/               Unit + integration stubs for all modules
docs/                Architecture, data flow, retrieval strategy, API contracts
scripts/             benchmark.py, seed_test_data.py
```

---

## License

MIT
