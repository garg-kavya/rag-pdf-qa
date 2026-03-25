"""
Memory Manager Tests
=====================

Purpose:
    Tests for the conversational memory subsystem: MemoryManager,
    ContextBuilder, and MemoryCompressor.

Test Cases:

    test_get_formatted_history_empty_session:
        A session with zero turns returns an empty string.

    test_get_formatted_history_single_turn:
        A session with one turn returns a correctly formatted Q&A block.

    test_get_formatted_history_token_budget_respected:
        When total history exceeds the token budget, oldest turns are dropped
        and the returned string fits within the budget.

    test_get_formatted_history_newest_turns_prioritised:
        When trimming due to budget, the most recent turns are retained
        (not the oldest).

    test_record_turn_appends_to_session:
        After record_turn(), the session's turn_count increases by 1.

    test_record_turn_stores_all_fields:
        The stored ConversationTurn contains user_query, standalone_query,
        assistant_response, retrieved_chunk_ids, citations, and timestamp.

    test_compression_triggered_at_threshold:
        When turn_count == COMPRESSION_THRESHOLD, compression is triggered.

    test_compression_replaces_oldest_turns_with_summary:
        After compression, the oldest N turns are replaced by a SummaryTurn,
        and the total turn count decreases by N-1.

    test_compression_summary_turn_rendered_correctly:
        ContextBuilder renders a SummaryTurn with the "Summary of earlier
        conversation:" prefix (not "User:").

    test_compression_not_triggered_below_threshold:
        When turn_count < COMPRESSION_THRESHOLD, no compression occurs.

    test_context_builder_formats_multiple_turns_chronologically:
        Multiple turns are output oldest-first in the formatted string.

Dependencies:
    - pytest
    - pytest-asyncio
    - app.memory.memory_manager
    - app.memory.context_builder
    - app.memory.memory_compressor
    - app.db.session_store (real in-memory instance)
    - tests.conftest (sample_session fixture)
"""
