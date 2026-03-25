"""
Memory Manager
===============

Purpose:
    Orchestrates all conversational memory operations for a single session.
    Acts as the interface between the RAG chain and the underlying persistence
    (SessionStore) and formatting (ContextBuilder, MemoryCompressor) layers.

    The RAG chain calls this module at two points:
    1. Before generation — to read formatted history for prompt injection.
    2. After generation — to persist the new turn and trigger compression
       if the session has grown long.

Responsibilities:

    Reading memory (pre-generation):
        1. Fetch the session's ConversationTurn list from SessionStore.
        2. Delegate to ContextBuilder to serialise turns into a prompt string,
           respecting a token budget (default: 1024 tokens for history).
        3. Return the formatted context string to the RAG chain.

    Writing memory (post-generation):
        1. Construct a new ConversationTurn from the completed query/response.
        2. Delegate to SessionStore.update_session() to append the turn.
        3. If turn_count > COMPRESSION_THRESHOLD, delegate to MemoryCompressor
           to summarise the oldest turns and replace them with a summary turn.

    Compression policy:
        Default COMPRESSION_THRESHOLD = MAX_CONVERSATION_TURNS (10).
        When turn_count reaches the threshold, the oldest 5 turns are replaced
        with a single SummaryTurn. This keeps history bounded while preserving
        context from early in the session.

Methods:

    get_formatted_history(
        session_id: str,
        token_budget: int = 1024
    ) -> str:
        Reads the session history and returns a formatted string for prompt
        injection. Applies token trimming if necessary.
        Inputs:
            session_id: the active session
            token_budget: max tokens to allocate to history in the prompt
        Outputs:
            Formatted history string (may be empty string for first turn)

    record_turn(
        session_id: str,
        user_query: str,
        standalone_query: str,
        assistant_response: str,
        retrieved_chunk_ids: list[str],
        citations: list[Citation]
    ) -> None:
        Persists a completed conversation turn. Triggers compression if needed.
        Inputs: all fields of a ConversationTurn plus Citation list
        Outputs: None (side effect: session store updated)

    get_turn_count(session_id: str) -> int:
        Returns the current number of turns in the session.

Dependencies:
    - app.db.session_store (SessionStore)
    - app.memory.context_builder (ContextBuilder)
    - app.memory.memory_compressor (MemoryCompressor)
    - app.models.session (ConversationTurn)
    - app.models.query (Citation)
    - app.config (SessionSettings)
"""
