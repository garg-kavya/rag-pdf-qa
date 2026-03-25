# Retrieval Strategy — RAG PDF Q&A System

---

## Pipeline Overview

The retrieval pipeline is a four-stage process owned by `RAGPipeline` and executed by `RetrieverService` and `RerankerService`.

```
EmbeddingCache.get_or_embed(standalone_query)
          │
          │  1536-dim query vector
          ▼
RetrieverService.retrieve(query_embedding, document_ids, TOP_K_CANDIDATES)
    │
    ├── Stage 1: VectorStore.search()       bi-encoder cosine similarity
    │             over-fetch top-10 candidates
    │
    └── Stage 2: Score threshold filter    discard score < 0.70
          │
          │  list[ScoredChunk] with bi_encoder_score set
          ▼
RerankerService.rerank(standalone_query, candidates)   [optional]
    │
    │  list[ScoredChunk] with similarity_score = reranker score
    │  (bi_encoder_score preserved for diagnostics)
    ▼
RetrieverService.apply_mmr(candidates, top_k=5)
    │
    │  final top-k diverse, relevant chunks
    ▼
RAGChain.invoke(query_context, retrieved_context)
```

---

## Stage 1: Vector Similarity Search

- **Algorithm:** Cosine similarity (dot product on L2-normalised vectors)
- **Index:** FAISS `IndexFlatIP` (exhaustive, exact) for datasets < 500K vectors
- **Scoping:** `document_ids` filter limits search to session documents
- **Over-fetch:** retrieves `TOP_K_CANDIDATES = TOP_K × 2` (default: 10)
  so the reranker and MMR have enough candidates to work with

FAISS latency: 10–50ms for typical PDF workloads (1K–100K vectors)

---

## Stage 2: Score Threshold Filtering

**Threshold:** `SIMILARITY_THRESHOLD = 0.70` (configurable)

Purpose: eliminate chunks that are in the top-10 by cosine distance but are not genuinely relevant. Prevents noise from reaching the LLM even when the query doesn't have strong document matches.

Calibration with `text-embedding-3-small`:
- 0.80+: very strong match (same topic + subtopic)
- 0.70–0.80: relevant match (same topic)
- 0.60–0.70: marginal (same domain, different topic)
- <0.60: unrelated

After this stage, each `ScoredChunk` has `bi_encoder_score` set and `similarity_score == bi_encoder_score`.

---

## Stage 3a: Cross-Encoder Reranking (optional)

**Purpose:** Improve relevance ordering. Unlike bi-encoder similarity (query and chunk embedded independently), a cross-encoder reads both texts together and scores their relevance jointly — fundamentally more accurate.

**When to use:**
- Disabled (`RERANKER_BACKEND=none`): rely on MMR-only ordering. Suitable for most use-cases.
- `cross_encoder`: local model, no cost, ~50–150ms. Best for development or when cost matters.
- `cohere`: higher quality, external API, ~200–400ms. Best for production.

**Score contract:**
- Input: `similarity_score == bi_encoder_score`
- Output: `rerank_score` = raw cross-encoder/Cohere score; `similarity_score` = normalised reranker score; `bi_encoder_score` preserved unchanged

**Failure handling:** `RerankerError` triggers fallback to bi-encoder ordering. The request never fails due to a reranker issue.

---

## Stage 3b: MMR Diversity Selection

**Formula:**
```
score(chunk_i) = λ · similarity_score(chunk_i, query)
               − (1−λ) · max(similarity_score(chunk_i, selected_j))
```

**λ = MMR_DIVERSITY_FACTOR = 0.7** (favour relevance, mild diversity)

**Purpose:** Prevents the top-k from being 5 near-identical chunks from the same paragraph. Forces coverage of different aspects of the answer.

**When MMR is skipped:** If `len(candidates) ≤ top_k`, all candidates are returned without MMR calculation (no diversity gain possible).

After MMR, each chunk has `rank` set (1-based). This is the final ordering passed to the LLM.

---

## Chunk Size Analysis

| Size | Semantic quality | Context | Precision@5 | 5-chunk context cost |
|---|---|---|---|---|
| 256 tokens | Low — splits ideas mid-thought | Poor | ~0.45–0.55 | 1,280 tokens |
| 384 tokens | Moderate | Moderate | ~0.55–0.65 | 1,920 tokens |
| **512 tokens** | **High — 1-2 paragraphs** | **Good** | **~0.70–0.85** | **2,560 tokens** |
| 768 tokens | Mixed topics in one chunk | Broad | ~0.55–0.65 | 3,840 tokens |
| 1,024 tokens | Diluted embedding signal | Very broad | ~0.45–0.55 | 5,120 tokens |

**Selected: 512 tokens**

Reasons:
1. Large enough to contain a complete idea with supporting detail
2. Small enough for the embedding to represent a focused concept
3. 5 × 512 = 2,560 tokens leaves room for system prompt (~200), history (~1,024) and generation (~1,024) within an 8K window

**Overlap: 64 tokens (12.5%)** — ensures boundary sentences appear in both adjacent chunks, preventing information loss at splits.

**Split hierarchy:** `\n\n` → `\n` → `. ` → ` ` — splits at the highest-level semantic boundary that keeps the chunk within budget.

---

## Top-K Tuning

| k | Use case | Notes |
|---|---|---|
| 3 | Simple factual lookup | Fast, minimal context |
| **5** | **General Q&A (default)** | **Best balance** |
| 7 | Analytical questions | Broader coverage |
| 10 | Synthesis / summarization | Maximum coverage, more noise |

Per-query override available via the API `top_k` parameter (range 3–10).

---

## Expected Precision@5 by Configuration

| Configuration | Estimated P@5 |
|---|---|
| 512 tokens, k=5, no reranker, no MMR | 0.55–0.65 |
| 512 tokens, k=5, no reranker, MMR | 0.65–0.75 |
| 512 tokens, k=5, cross-encoder, MMR | **0.75–0.85** |
| 512 tokens, k=5, Cohere, MMR | **0.78–0.88** |

Run `scripts/benchmark.py` to measure actual P@5 on your document set.

---

## Latency by Configuration

| Retrieval config | Retrieval latency | Total to first token |
|---|---|---|
| FAISS, no reranker | ~60ms | ~750–1000ms |
| FAISS, cross-encoder | ~160ms | ~850–1150ms |
| FAISS, Cohere reranker | ~350ms | ~1050–1350ms |
| ChromaDB, no reranker | ~100ms | ~800–1050ms |

All configurations remain within the 2-second target for time to first token.
