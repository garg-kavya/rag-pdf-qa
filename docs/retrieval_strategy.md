# Retrieval Strategy — DocMind

---

## Query Reformulation (Pre-Retrieval)

Before the retrieval pipeline runs, `QueryReformulator` expands the raw query into a more searchable form. This step **always runs** (not conditional on conversation history).

Two transformations:

1. **Coreference resolution** — anchors follow-up queries to their subjects:
   > "What about their revenue?" → "What was Acme Corp's Q3 2024 revenue?"

2. **Inference expansion** — rewrites vague evaluation questions into explicit search terms:
   > "Is he a bad guy?" → "professional misconduct unethical behaviour criminal record character flaws"
   > "Should I hire her?" → "qualifications skills experience achievements suitability"

The expanded `standalone_query` is what gets embedded and passed to the vector store — dramatically improving recall for indirect questions.

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
    │             over-fetch top-20 candidates
    │
    └── Stage 2: Score threshold filter    discard score < SIMILARITY_THRESHOLD
          │                                (default: 0.0 = disabled)
          │  list[ScoredChunk] with bi_encoder_score set
          ▼
RerankerService.rerank(standalone_query, candidates)   [optional]
    │
    │  list[ScoredChunk] with similarity_score = reranker score
    │  (bi_encoder_score preserved for diagnostics)
    ▼
RetrieverService.apply_mmr(candidates, top_k=10)
    │
    │  final top-k diverse, relevant chunks
    ▼
RAGChain.invoke(query_context, retrieved_context)
```

---

## Stage 1: Vector Similarity Search

- **Algorithm:** Cosine similarity (dot product on L2-normalised vectors)
- **Index:** ChromaDB persistent collection (default); FAISS `IndexFlatIP` (optional)
- **Scoping:** `document_ids` filter limits search to session documents
- **Over-fetch:** retrieves `TOP_K_CANDIDATES = 20` (= `TOP_K × 2`)
  so the reranker and MMR have enough candidates to work with

ChromaDB latency: 10–100ms for typical PDF workloads (1K–100K vectors)

---

## Stage 2: Score Threshold Filtering

**Threshold:** `SIMILARITY_THRESHOLD = 0.0` (default: disabled)

With `text-embedding-3-small`, cosine similarity for semantically related (but not near-identical) text typically falls in the **0.10–0.29** range — far below the 0.70 threshold used in dense retrieval systems. The default of `0.0` disables filtering so all retrieved candidates proceed to MMR.

If you are seeing irrelevant chunks in answers, calibrate against your document set:
- 0.25+: strong semantic overlap
- 0.15–0.25: relevant match
- 0.05–0.15: marginal
- <0.05: likely unrelated

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
               − (1−λ) · max_diversity_penalty(chunk_i, selected)
```

**Diversity signal** (chunk position distance):
- Same document: `penalty = 1 / (1 + |chunk_index_i − chunk_index_j|)`
  → adjacent chunks (dist ≤ 1) penalized heavily; distant chunks allowed
- Different document: `penalty = 0.0` (maximally diverse by definition)

**λ = MMR_DIVERSITY_FACTOR = 0.7** (favour relevance, mild diversity)

**Purpose:** Prevents the top-k from being near-identical adjacent chunks from the same paragraph. Forces coverage of different sections and documents.

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
| 5 | Narrow Q&A | Lower noise |
| **10** | **General Q&A (default)** | **Best balance for inference queries** |
| 15 | Synthesis / summarization | Maximum coverage, more noise |

Per-query override available via the API `top_k` parameter (range 3–15). The higher default (10) is intentional — inference queries ("Is he a bad guy?") need broader evidence coverage to draw conclusions from sparse signal.

---

## Expected Precision@10 by Configuration

| Configuration | Estimated P@10 |
|---|---|
| 512 tokens, k=10, no reranker, no MMR | 0.50–0.60 |
| 512 tokens, k=10, no reranker, MMR | 0.60–0.70 |
| 512 tokens, k=10, cross-encoder, MMR | **0.70–0.82** |
| 512 tokens, k=10, Cohere, MMR | **0.74–0.86** |

Run `scripts/benchmark.py` to measure actual P@5 on your document set.

---

## Latency by Configuration

| Retrieval config | Retrieval latency | Total to first token |
|---|---|---|
| ChromaDB, no reranker | ~100ms | ~850–1100ms |
| ChromaDB, cross-encoder | ~200ms | ~950–1200ms |
| ChromaDB, Cohere reranker | ~400ms | ~1150–1450ms |
| FAISS, no reranker | ~60ms | ~800–1050ms |

All configurations remain within the 2-second target for time to first token.
