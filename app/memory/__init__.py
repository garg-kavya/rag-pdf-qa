"""
Conversational Memory Package
===============================

Purpose:
    Provides the full conversational memory subsystem for multi-turn Q&A.
    Distinct from app.db.session_store (which handles session CRUD) — this
    package is responsible for what memory is built, how it's shaped for
    prompt injection, and when it's compressed.

Modules:

    memory_manager
        Orchestrates memory operations for a session. The single entry point
        that the RAG chain calls to read/write conversational context.

    context_builder
        Converts raw ConversationTurn objects into a formatted string block
        ready for injection into the LLM prompt. Handles token budgeting —
        trims oldest turns if the serialised history exceeds the budget.

    memory_compressor
        Summarises old conversation turns when the session is long. Instead
        of dropping old turns entirely, compresses them into a brief summary
        so long-running sessions retain their full context.

Relationship to app.db.session_store:
    session_store  — persistence layer (CRUD, TTL, cleanup)
    memory/        — intelligence layer (what to keep, how to format it)

    The RAG chain calls MemoryManager, which reads from SessionStore,
    transforms the history via ContextBuilder, and writes back via SessionStore.
"""
