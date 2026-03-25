"""
RAG Chain — LLM Interaction Layer
===================================

Purpose:
    Defines the LangChain/LangGraph chain responsible ONLY for LLM interaction:
    prompt assembly, OpenAI Chat API call, token streaming, and citation
    extraction from the raw LLM output.

    This module is NOT the pipeline orchestrator. It does not know about
    caches, the reranker, session management, or memory compression.
    Those concerns live in app/pipeline/rag_pipeline.py.

    Calling convention (established by RAGPipeline):
        RAGPipeline prepares a fully-populated QueryContext and
        RetrievedContext, then hands them to RAGChain.invoke() or
        RAGChain.stream(). The chain's only job is to turn those inputs
        into a GeneratedAnswer.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Responsibilities of THIS module
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    1. Prompt Assembly
       - Build the full prompt from templates in app/chains/prompts.py:
           system_prompt
           + numbered context block (from retrieved chunks)
           + conversation history block (from query_context.formatted_history)
           + user question (standalone_query)
       - Apply context-window budget: if total tokens exceed LLM_MAX_CONTEXT,
         drop the lowest-scored chunks (not the history — history is already
         budgeted by MemoryManager).

    2. LLM Call
       - Call OpenAI Chat Completion (non-streaming) or streaming API.
       - Temperature and max_tokens from OpenAISettings.
       - On timeout: retry once with same payload.
       - On non-retryable error: raise GenerationAPIError.

    3. Citation Extraction (post-generation)
       - Parse [Source N] references in the generated text.
       - Map each reference to the corresponding ScoredChunk metadata.
       - Build structured Citation objects.
       - Validate: discard references to source numbers not in the context
         (hallucination guard — the LLM cited a source it wasn't given).
       - On CitationExtractionError: log warning, return empty citations
         rather than failing the request.

    4. Confidence Scoring
       - Heuristic: mean(similarity_score) × citation_density_factor
         × uncertainty_penalty (if LLM output contains "I don't know" etc.)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOT Responsibilities of THIS module
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    ✗ Session lookup / validation           → RAGPipeline
    ✗ Query reformulation                   → QueryReformulator (via RAGPipeline)
    ✗ Query embedding                       → EmbeddingCache (via RAGPipeline)
    ✗ Vector search / retrieval             → RetrieverService (via RAGPipeline)
    ✗ Reranking                             → RerankerService (via RAGPipeline)
    ✗ MMR selection                         → RetrieverService (via RAGPipeline)
    ✗ Reading conversation history          → MemoryManager (via RAGPipeline)
    ✗ Writing conversation history          → MemoryManager (via RAGPipeline)
    ✗ Response caching                      → ResponseCache (via RAGPipeline)
    ✗ SSE formatting / StreamingResponse    → StreamingHandler (via RAGPipeline)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LangGraph Implementation Note
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    The chain is implemented as a LangGraph StateGraph with two nodes:
        "assemble_prompt"  → builds ChatPromptTemplate messages
        "call_llm"         → invokes the model, extracts citations

    LangGraph is used here (not LCEL) for:
    - Built-in streaming support without boilerplate
    - Conditional edge for context truncation
    - Typed state (ChainState dataclass) flowing between nodes

    ChainState:
        query_context: QueryContext
        retrieved_context: RetrievedContext
        prompt_messages: list[ChatMessage] | None  (populated by assemble_prompt)
        raw_llm_output: str | None                 (populated by call_llm)
        generated_answer: GeneratedAnswer | None   (populated by call_llm)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Methods
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    invoke(
        query_context: QueryContext,
        retrieved_context: RetrievedContext
    ) -> GeneratedAnswer:
        Synchronous (non-streaming) chain execution.
        Inputs:
            query_context    — fully populated by RAGPipeline (all fields set)
            retrieved_context — ranked chunks from retriever + reranker + MMR
        Outputs:
            GeneratedAnswer (answer_text, citations, confidence)
            Does NOT set query_id, cache_hit, or pipeline_metadata —
            those are set by RAGPipeline before returning to the API.

    stream(
        query_context: QueryContext,
        retrieved_context: RetrievedContext
    ) -> AsyncGenerator[StreamingChunk, None]:
        Streaming chain execution via LangGraph.stream().
        Yields StreamingChunk events (event="token" per token).
        Does NOT yield citation or done events — RAGPipeline wraps this
        generator and appends those final events.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Dependencies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    langchain / langgraph
    openai (AsyncOpenAI)
    app.chains.prompts     (SYSTEM_PROMPT, CONTEXT_TEMPLATE, etc.)
    app.models.query       (QueryContext, RetrievedContext, GeneratedAnswer,
                            Citation, StreamingChunk)
    app.exceptions         (GenerationAPIError, GenerationTimeoutError,
                            ContextTooLongError, CitationExtractionError)
    app.config             (OpenAISettings)
    app.utils.token_counter (count_tokens — for context window budget)
"""
