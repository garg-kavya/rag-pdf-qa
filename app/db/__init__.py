"""
Database / Storage Layer
=========================

Provides all persistence abstractions for the system:

    vector_store        → Abstract interface for vector DB operations
    faiss_store         → FAISS in-memory implementation (fast, default)
    chroma_store        → ChromaDB persistent implementation
    session_store       → In-memory session CRUD with TTL cleanup
    document_registry   → In-memory document status and metadata registry
"""
