# Data Flow — RAG PDF Q&A System

---

## Flow 1: PDF Ingestion

```
Client: POST /api/v1/documents/upload (multipart/form-data)
              │
              ▼
┌─────────────────────────────────────────────────────────────────┐
│ API Handler (documents.py)                                      │
│ 1. Validate MIME = application/pdf                              │
│ 2. Validate size ≤ MAX_UPLOAD_SIZE_MB                           │
│ 3. FileUtils.save_upload() → (file_path, document_id)          │
│ 4. DocumentRegistry.register(document_id, ...) → status=uploaded│
│ 5. Launch IngestionPipeline.run() as BackgroundTask             │
│ 6. Return 202 Accepted immediately                              │
└──────────────────────────────┬──────────────────────────────────┘
                               │ (background)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ IngestionPipeline.run()                                         │
│                                                                 │
│ Step 1: DocumentRegistry.update_status(→ "processing")         │
│                                                                 │
│ Step 2: PDFProcessorService.parse(file_path, document_id)      │
│   ├── PyMuPDF (primary): ~100 pages/sec                        │
│   ├── pdfplumber (fallback if chars_per_page < threshold)      │
│   └── ParsedDocument {pages, pdf_metadata, parser_used}        │
│   On PDFParsingError → status="error", re-raise                │
│                                                                 │
│ Step 3: TextCleanerService.clean(parsed_document)              │
│   └── cleaned_text, page_boundary_offsets                      │
│                                                                 │
│ Step 4: ChunkerService.chunk(cleaned_text, ..., document_id)   │
│   ├── Recursive character split: 512 tokens, 64 overlap        │
│   └── list[Chunk] with {chunk_id, chunk_index, page_numbers,   │
│         token_count, text, start/end_char_offset}               │
│                                                                 │
│ Step 5: EmbedderService.embed_chunks(chunks)                   │
│   ├── Batch OpenAI calls (100 chunks/batch)                    │
│   └── Each chunk.embedding ← 1536-dim float32 vector          │
│   On EmbeddingAPIError → status="error", re-raise              │
│                                                                 │
│ Step 6: VectorStore.add_chunks(chunks)                         │
│   └── Stores vectors + ChunkMetadata per chunk                 │
│   On StorageWriteError → status="error", re-raise              │
│                                                                 │
│ Step 7: DocumentRegistry.update_status(→ "ready")              │
│         DocumentRegistry.set_ingestion_metadata(...)           │
│                                                                 │
│ Step 8 (optional): SessionStore.add_document_to_session(...)   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Flow 2: Query — Non-Streaming

```
Client: POST /api/v1/query
        {"question": "...", "session_id": "...", "top_k": 5}
              │
              ▼
┌─────────────────────────────────────────────────────────────────┐
│ API Handler (query.py)                                          │
│ 1. Validate QueryRequest (Pydantic)                            │
│ 2. RAGPipeline.run(question, session_id, document_ids, top_k)  │
│ 3. Map GeneratedAnswer → QueryResponse                         │
│ 4. Return 200 OK                                               │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ RAGPipeline.run()                                               │
│                                                                 │
│ Step 1: SessionStore.get_session(session_id)                   │
│   └── Extract: document_ids, turn_count, conversation_history  │
│   On not found → SessionNotFoundError (→ 404)                  │
│   On empty docs → NoDocumentsError (→ 409)                     │
│                                                                 │
│ Step 2: ResponseCache.get_or_generate(                         │
│           query, session_id, document_ids, turn_count,         │
│           generate_fn=<steps 3-11>)                            │
│   HIT  → return cached GeneratedAnswer (cache_hit=True)        │
│   MISS → continue ↓                                            │
│                                                                 │
│ Step 3: Query Reformulation (conditional)                      │
│   IF turn_count == 0:  standalone_query = raw_query  (0ms)    │
│   ELSE: QueryReformulator.reformulate(query, history)          │
│         Example: "What about their revenue?"                   │
│             → "What was Acme Corp's Q3 2024 revenue?"          │
│                                                                 │
│ Step 4: EmbeddingCache.get_or_embed(standalone_query)          │
│   HIT  → return cached 1536-dim vector  (~1ms)                │
│   MISS → EmbeddingService.embed_query() → store  (~150ms)     │
│                                                                 │
│ Step 5: RetrieverService.retrieve(                             │
│           query_embedding, document_ids, TOP_K_CANDIDATES=10)  │
│   Stage 1: VectorStore.search() → top-10 candidates           │
│   Stage 2: discard score < SIMILARITY_THRESHOLD (0.70)        │
│   Output: list[ScoredChunk] (bi_encoder_score set)             │
│                                                                 │
│ Step 6: Reranking (conditional)                                │
│   IF RerankerService.is_enabled():                             │
│     RerankerService.rerank(standalone_query, candidates)       │
│     → similarity_score ← reranker score                       │
│     → bi_encoder_score preserved for diagnostics              │
│     → rerank_score set                                         │
│   ELSE: candidates unchanged                                   │
│   On RerankerError → log warning, fall back to bi-encoder      │
│                                                                 │
│ Step 7: RetrieverService.apply_mmr(candidates, top_k=5)        │
│   MMR: λ·relevance − (1−λ)·max_sim_to_selected               │
│   Output: final top-5 list[ScoredChunk] (rank set)             │
│                                                                 │
│ Step 8: MemoryManager.get_formatted_history(                   │
│           session_id, token_budget=1024)                       │
│   ContextBuilder serialises history ≤ 1024 tokens              │
│   (trims oldest turns first if over budget)                    │
│   Output: formatted_history string → QueryContext              │
│                                                                 │
│ Step 9: QueryContext assembled (all fields populated):         │
│   raw_query, standalone_query, query_id (new UUID),            │
│   session_id, document_ids, query_embedding,                   │
│   formatted_history, reranker_applied, cache_hit=False         │
│                                                                 │
│ Step 10: RAGChain.invoke(query_context, retrieved_context)     │
│   ├── Assemble prompt:                                         │
│   │     system + context_block + history + question            │
│   ├── OpenAI ChatCompletion (gpt-4o, temperature=0.1)          │
│   ├── Parse [Source N] citations from output                   │
│   └── Build GeneratedAnswer (answer_text, citations, confidence│
│   On GenerationAPIError → 502                                  │
│   On ContextTooLongError → truncate lowest-scored chunks, retry│
│                                                                 │
│ Step 11: MemoryManager.record_turn(session_id, ...)            │
│   → Append ConversationTurn to session                         │
│   → Trigger MemoryCompressor if turn_count ≥ threshold        │
│                                                                 │
│ Return: GeneratedAnswer (+ pipeline_metadata with all timings) │
└─────────────────────────────────────────────────────────────────┘
```

---

## Flow 3: Query — Streaming (SSE)

Steps 1, 3-9 are identical to Flow 2.

Step 2 (ResponseCache) is **skipped** — streaming cannot be replayed.

```
│ Step 10 (streaming): RAGChain.stream(query_context, retrieved)  │
│   ├── Assemble prompt (same as sync)                            │
│   ├── OpenAI ChatCompletion with stream=True                    │
│   └── Yield tokens as they arrive                               │
│                                                                 │
│   StreamingHandler wraps the generator as SSE:                 │
│                                                                 │
│     event: token                                                │
│     data: {"text": "The", "query_id": "abc-123"}               │
│     ... (one per token)                                         │
│                                                                 │
│     event: citation                                             │
│     data: {"citations": [...], "query_id": "abc-123"}           │
│                                                                 │
│     event: done                                                 │
│     data: {"query_id": "abc-123", "total_tokens": 142,          │
│             "reranker_applied": true, "confidence": 0.87}       │
│                                                                 │
│ Step 11: MemoryManager.record_turn() — after stream exhausted   │
```

---

## Latency Budget

| Stage | Typical | Worst Case | Notes |
|---|---|---|---|
| Session lookup | <1ms | <1ms | in-memory |
| Response cache check | <1ms | <1ms | cache hit returns immediately |
| Query reformulation | 0–300ms | 500ms | skipped on first turn |
| Query embedding | 1–150ms | 300ms | near-zero on cache hit |
| Vector search | 10–50ms | 100ms | FAISS in-memory |
| Threshold filter | <1ms | <1ms | CPU only |
| Cross-encoder reranking | 0–400ms | 600ms | 0 when disabled |
| MMR selection | 5–20ms | 50ms | CPU only |
| Memory read | <1ms | <1ms | in-memory |
| LLM first token | 300–500ms | 800ms | OpenAI streaming |
| **Total to first token** | **~650–1200ms** | **~1850ms** | **≤ 2s target** |

---

## Data Model Flow

```
Upload                        Query
  │                              │
  ▼                              ▼
PDFMetadata              QueryContext {
IngestionMetadata    →       raw_query, standalone_query,
        │                    query_id, session_id,
        ▼                    document_ids, query_embedding,
ChunkMetadata                formatted_history,
(stored in VectorDB)         reranker_applied, cache_hit
                         }
                              │
                              ▼
                         RetrievedContext {
                             chunks: list[ScoredChunk {
                                 chunk, similarity_score,
                                 bi_encoder_score,
                                 rerank_score, rank
                             }],
                             retrieval_metadata: RetrievalMetadata
                         }
                              │
                              ▼
                         GeneratedAnswer {
                             answer_text, citations,
                             confidence, query_id,
                             cache_hit,
                             retrieval_context,
                             pipeline_metadata: PipelineMetadata
                         }
```
