# Architecture — RAG PDF Q&A System

## Overview

A production-grade Retrieval-Augmented Generation system for answering questions over uploaded PDF documents with conversational memory, source citations, and low-latency streaming.

Every answer is grounded exclusively in uploaded PDF content. No prior knowledge leaks from the LLM.

---

## Layer Model

```
┌───────────────────────────────────────────────────────────────────┐
│                         CLIENT                                    │
│        PDF Upload                     Question                    │
└───────────────┬───────────────────────────────┬───────────────────┘
                │                               │
                ▼                               ▼
┌───────────────────────────────────────────────────────────────────┐
│                      API LAYER  (app/api/)                        │
│  /documents/upload          /query          /query/stream         │
│  /sessions                  /health                               │
│  Thin handlers: validate → delegate → map response                │
└───────────────┬───────────────────────────────┬───────────────────┘
                │                               │
                ▼                               ▼
┌─────────────────────────┐   ┌─────────────────────────────────────┐
│  INGESTION PIPELINE     │   │  RAG PIPELINE  (app/pipeline/)      │
│  (app/pipeline/)        │   │                                     │
│                         │   │  Single entry point for all         │
│  Orchestrates:          │   │  query-answer operations.           │
│  PDF parse → clean      │   │  Orchestrates: cache check →        │
│  → chunk → embed        │   │  reformulate → embed (cached) →     │
│  → vector store         │   │  retrieve → rerank → MMR →          │
│  → registry update      │   │  memory read → generate (cached) → │
│                         │   │  memory write                       │
└─────────────────────────┘   └─────────────────────────────────────┘
                │                               │
                └───────────────┬───────────────┘
                                │ calls
          ┌─────────────────────┼──────────────────────────┐
          │                     │                          │
          ▼                     ▼                          ▼
┌──────────────────┐  ┌─────────────────────┐  ┌──────────────────┐
│  SERVICES        │  │  CACHE LAYER        │  │  MEMORY LAYER    │
│  (app/services/) │  │  (app/cache/)       │  │  (app/memory/)   │
│                  │  │                     │  │                  │
│  pdf_processor   │  │  EmbeddingCache     │  │  MemoryManager   │
│  text_cleaner    │  │    sha256(query)    │  │    orchestrates  │
│  chunker         │  │    → 24h TTL        │  │                  │
│  embedder        │  │                     │  │  ContextBuilder  │
│  retriever       │  │  ResponseCache      │  │    token-budgets │
│  reranker        │  │    (session,query,  │  │    history       │
│  generator       │  │     docs, turns)    │  │                  │
│  query_reformulator  │    → 60s TTL       │  │  MemoryCompressor│
│  streaming       │  │                     │  │    summarises    │
└──────────────────┘  └─────────────────────┘  │    old turns     │
          │                     │               └──────────────────┘
          │                     │
          ▼                     ▼
┌──────────────────────────────────────────────────────────────────┐
│  CHAINS LAYER  (app/chains/)                                     │
│  LLM-specific only: prompt assembly, OpenAI call, citation parse │
│  RAGChain (LangGraph) — called by RAGPipeline only               │
└──────────────────────────────────────────────────────────────────┘
          │                     │
          ▼                     ▼
┌─────────────────┐   ┌──────────────────────────────────────────┐
│  DB / STORAGE   │   │  DOMAIN MODELS + SCHEMAS                 │
│  (app/db/)      │   │  (app/models/, app/schemas/)             │
│                 │   │                                          │
│  VectorStore    │   │  QueryContext, ScoredChunk,              │
│  FAISSStore     │   │  GeneratedAnswer, PipelineMetadata       │
│  ChromaStore    │   │  ChunkMetadata, RetrievalMetadata        │
│  SessionStore   │   │  (typed, validated, single source of     │
│  DocumentReg.   │   │   truth for all data shapes)             │
└─────────────────┘   └──────────────────────────────────────────┘
```

---

## Component Reference

### API Layer (`app/api/`)

| Endpoint | Handler | Delegates to |
|---|---|---|
| `POST /documents/upload` | `documents.py` | `IngestionPipeline.run()` (BackgroundTask) |
| `GET /documents/{id}` | `documents.py` | `DocumentRegistry.get()` |
| `DELETE /documents/{id}` | `documents.py` | `VectorStore.delete_document()` + `DocumentRegistry.delete()` |
| `POST /query` | `query.py` | `RAGPipeline.run()` |
| `POST /query/stream` | `query.py` | `RAGPipeline.run_stream()` |
| `POST /sessions` | `sessions.py` | `SessionStore.create_session()` |
| `GET /sessions/{id}` | `sessions.py` | `SessionStore.get_session()` |
| `DELETE /sessions/{id}` | `sessions.py` | `SessionStore.delete_session()` |
| `GET /health` | `health.py` | VectorStore + OpenAI + DocumentRegistry stats |

### Pipeline Layer (`app/pipeline/`)

**`rag_pipeline.py`** — the single orchestrator for all query operations. No service, cache, or memory module is called by the API or by other services — only by this pipeline.

**`ingestion_pipeline.py`** — the single orchestrator for all PDF ingestion. Called as a FastAPI `BackgroundTask` after the API handler returns 202.

### Services Layer (`app/services/`)

Each service has a single responsibility and knows nothing about caches, memory, or the pipeline order.

| Service | Responsibility |
|---|---|
| `pdf_processor` | Parse PDF (PyMuPDF → pdfplumber fallback) |
| `text_cleaner` | Normalize extracted text (6 operations) |
| `chunker` | Split text into 512-token chunks with overlap |
| `embedder` | Batch embed chunks via OpenAI API |
| `retriever` | Vector search + threshold filter + MMR selection |
| `reranker` | Cross-encoder second-pass relevance scoring (optional) |
| `generator` | (moved to chains layer — see below) |
| `query_reformulator` | Resolve follow-up queries into standalone questions |
| `streaming` | Format SSE events from async token generator |

### Chains Layer (`app/chains/`)

Narrowed to LLM-only concerns. Called exclusively by `RAGPipeline`.

| Module | Responsibility |
|---|---|
| `rag_chain.py` | Build prompt, call OpenAI, extract citations, score confidence |
| `prompts.py` | All prompt templates (system, context, history, reformulation) |

### Cache Layer (`app/cache/`)

| Module | What is cached | Key | TTL |
|---|---|---|---|
| `embedding_cache` | Query embeddings | sha256(normalised query) | 24h |
| `response_cache` | Full `GeneratedAnswer` | sha256(session+query+docs+turns) | 60s |
| `in_memory_cache` | Backend (LRU dict) | — | configurable |
| `cache_backend` | Abstract interface | — | — |

### Memory Layer (`app/memory/`)

| Module | Responsibility |
|---|---|
| `memory_manager` | Orchestrates memory read (pre-generation) and write (post-generation) |
| `context_builder` | Serialises `ConversationTurn` list into token-budgeted history string |
| `memory_compressor` | Summarises oldest N turns when session exceeds threshold |

### DB / Storage Layer (`app/db/`)

| Module | Responsibility |
|---|---|
| `vector_store` | Abstract interface: add_chunks, search, delete_document |
| `faiss_store` | FAISS IndexFlatIP + parallel metadata dict |
| `chroma_store` | ChromaDB persistent collection |
| `session_store` | In-memory session CRUD with TTL expiry |
| `document_registry` | In-memory document status and metadata tracking |

---

## Key Design Decisions

### 1. Pipeline Layer Separates Orchestration from Services
`RAGPipeline` owns the stage order and wiring. Services, caches, and memory modules are independent — none call each other directly. This makes each unit testable in isolation and the pipeline swappable.

### 2. Chains Layer is LLM-Only
`rag_chain.py` does not know about sessions, caches, reranking, or memory. It receives a fully-populated `QueryContext` and `RetrievedContext` and returns a `GeneratedAnswer`. This makes it easy to swap LangGraph for a different framework.

### 3. Reranker is Optional and Graceful
`is_enabled()` guards the reranking step. When disabled, the pipeline is identical to the pre-reranker design (MMR-only). When the reranker fails, it logs a warning and falls back to bi-encoder ordering — the request never fails due to a reranker error.

### 4. Two-Level Caching
- **Embedding cache** (24h): eliminates the most common bottleneck (repeated queries).
- **Response cache** (60s): eliminates double-submission LLM calls; includes `turn_count` in the key to prevent stale answers.

### 5. Memory Layer Above Storage Layer
`session_store` handles persistence (CRUD, TTL). `memory_manager` handles intelligence (what to keep, how to format it, when to compress). Keeping them separate means the storage layer is replaceable (e.g., Redis) without touching memory logic.

### 6. DocumentRegistry Separates Document State from Vectors
Document status, PDF metadata, and ingestion results are stored in `DocumentRegistry`. Chunk vectors are stored in `VectorStore`. Neither knows about the other; `IngestionPipeline` coordinates them.

---

## Scalability Path

| Scale | Vector Store | Sessions | Deployment |
|---|---|---|---|
| Dev | FAISS (in-memory) | In-memory dict | Single container |
| Small prod | ChromaDB (persistent) | In-memory + Redis eviction | Docker Compose |
| Large prod | Pinecone / Weaviate | Redis Cluster | Kubernetes |
