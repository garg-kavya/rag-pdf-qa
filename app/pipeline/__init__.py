"""
Pipeline Package — Central Orchestration Layer
================================================

Purpose:
    Contains the two top-level orchestrators that drive all end-to-end
    workflows. Every API handler delegates directly to one of these
    orchestrators rather than calling individual services.

    Placing orchestration here (not in app/chains/) enforces a clean
    separation of concerns:

    ┌──────────────┐   delegates to   ┌──────────────────────────────────┐
    │  API Layer   │ ───────────────► │  Pipeline (orchestrators)        │
    │ (app/api/)   │                  │  rag_pipeline, ingestion_pipeline │
    └──────────────┘                  └──────────────┬───────────────────┘
                                                     │ calls
                              ┌──────────────────────┼──────────────────┐
                              │                      │                  │
                        ┌─────▼─────┐   ┌────────────▼─────┐   ┌───────▼──────┐
                        │ Services  │   │  Cache Layer      │   │  Memory      │
                        │ retriever │   │  EmbeddingCache   │   │  MemoryMgr   │
                        │ reranker  │   │  ResponseCache    │   │  ContextBdr  │
                        │ generator │   └──────────────────-┘   └──────────────┘
                        └─────┬─────┘
                              │ calls (LLM specifics only)
                        ┌─────▼─────┐
                        │  Chains   │
                        │ rag_chain │
                        │ prompts   │
                        └───────────┘

Modules:

    rag_pipeline
        Orchestrates the full query-answer cycle:
        session resolution → reformulation → embedding (cached) →
        retrieval → reranking → memory read → generation (cached) →
        memory write → response.

    ingestion_pipeline
        Orchestrates the full PDF ingestion cycle:
        validation → parsing → cleaning → chunking →
        embedding (batch) → vector storage → status update.
"""
