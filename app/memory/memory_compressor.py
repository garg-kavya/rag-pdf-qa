"""
Memory Compressor
==================

Purpose:
    Summarises the oldest conversation turns in a session when the history
    grows beyond the compression threshold. Prevents context window overflow
    for long sessions while retaining the gist of earlier exchanges.

    Without compression, sessions reaching MAX_CONVERSATION_TURNS (10) simply
    drop the oldest turns. This loses information that may be referenced later
    ("go back to what you said about X earlier"). Compression preserves a
    compact representation of those early turns.

Strategy:
    When MemoryManager detects turn_count > COMPRESSION_THRESHOLD:
    1. Take the oldest N turns (default N=5).
    2. Serialise them as a Q&A transcript.
    3. Call the LLM with a summarisation prompt: "Summarise the following
       conversation concisely, preserving all factual details mentioned."
    4. Replace the N turns with a single SummaryTurn containing the summary.
    5. Remaining (recent) turns are kept verbatim.

    Result: a session with 10 turns becomes a session with 1 summary turn
    + 5 recent verbatim turns, keeping total token cost bounded.

SummaryTurn:
    A special ConversationTurn subtype used by ContextBuilder to render
    the summary with a distinct prefix ("Summary of earlier conversation:").
    Fields:
        is_summary: bool = True
        summary_text: str       — the compressed summary
        turns_covered: int      — how many original turns this replaces
        original_turn_range: tuple[int, int]  — (first_index, last_index)

Methods:

    compress(
        turns: list[ConversationTurn],
        n_turns_to_compress: int = 5
    ) -> list[ConversationTurn]:
        Takes the full turn list; compresses the oldest n_turns_to_compress
        into a summary; returns the modified list.
        Inputs:
            turns: full session history (oldest first)
            n_turns_to_compress: how many of the oldest turns to collapse
        Outputs:
            Modified list: [SummaryTurn] + remaining verbatim turns
        Side effects: one LLM API call (gpt-4o-mini, cheap summarisation task)

    should_compress(turn_count: int) -> bool:
        Returns True if compression should be triggered.
        Threshold: COMPRESSION_THRESHOLD from app.config.SessionSettings.

Dependencies:
    - openai (AsyncOpenAI — for summarisation call)
    - app.models.session (ConversationTurn)
    - app.config (SessionSettings, OpenAISettings)
"""
