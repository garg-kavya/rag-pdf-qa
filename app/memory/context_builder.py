"""
Context Builder
================

Purpose:
    Converts raw ConversationTurn objects into a formatted string block
    ready for injection into the LLM generation prompt. Handles the
    token-budget constraint so the history never overflows the context window.

Problem:
    A naive approach appends all prior turns to the prompt. For long sessions
    this blows the context window, causing:
    - Truncation of the retrieved chunks (reducing answer quality)
    - OpenAI API errors (prompt too long)
    - Increased cost per request

Approach:
    1. Iterate over turns from newest to oldest (most recent turns are most
       relevant for follow-up question resolution).
    2. Count tokens of each turn using token_counter.count_tokens().
    3. Include turns until the running token count reaches the budget.
    4. Older turns that don't fit are omitted (or replaced by a summary
       turn if MemoryCompressor has already summarised them).

Format:
    Each included turn is serialised as:

        "User: {user_query}
         Assistant: {assistant_response}"

    Turns are separated by a blank line. Oldest included turn appears first
    so the LLM reads history in chronological order.

    If a summary turn is present (produced by MemoryCompressor) it is
    prefixed with "Summary of earlier conversation:" instead of "User:".

Methods:

    build(
        turns: list[ConversationTurn],
        token_budget: int = 1024
    ) -> str:
        Converts a list of ConversationTurn objects to a formatted history string.
        Inputs:
            turns: ordered list (oldest first) from the session
            token_budget: max tokens the returned string may consume
        Outputs:
            Formatted multi-line string. Empty string if no turns fit.

    estimate_tokens(turns: list[ConversationTurn]) -> int:
        Returns total token count of all turns without applying a budget.
        Used by MemoryManager to decide whether compression is needed.

Dependencies:
    - app.models.session (ConversationTurn)
    - app.utils.token_counter (count_tokens)
"""
