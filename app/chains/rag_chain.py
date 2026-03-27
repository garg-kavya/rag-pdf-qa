"""RAG Chain — LLM interaction layer (prompt + OpenAI call + citations)."""
from __future__ import annotations

import re
from typing import AsyncGenerator

from openai import AsyncOpenAI

from app.chains.prompts import (
    CONTEXT_TEMPLATE,
    NO_CONTEXT_RESPONSE,
    SYSTEM_PROMPT,
    build_context_block,
)
from app.config import Settings
from app.exceptions import GenerationAPIError, GenerationTimeoutError
from app.models.query import (
    Citation,
    GeneratedAnswer,
    PipelineMetadata,
    QueryContext,
    RetrievedContext,
    StreamingChunk,
)
from app.utils.logging import get_logger
from app.utils.token_counter import count_tokens

logger = get_logger(__name__)


class RAGChain:
    """LLM-only: prompt assembly → OpenAI call → citation extraction."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.llm_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens
        self._max_context_tokens = 6000  # leave room for prompt + generation

    async def invoke(
        self,
        query_context: QueryContext,
        retrieved_context: RetrievedContext,
    ) -> GeneratedAnswer:
        messages = self._build_messages(query_context, retrieved_context)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:
            raise GenerationAPIError(f"OpenAI generation failed: {exc}") from exc

        answer_text = response.choices[0].message.content or ""
        citations = self._extract_citations(answer_text, retrieved_context)
        confidence = self._compute_confidence(answer_text, retrieved_context, citations)

        return GeneratedAnswer(
            answer_text=answer_text,
            citations=citations,
            confidence=confidence,
            query_id=query_context.query_id,
            cache_hit=False,
            retrieval_context=retrieved_context,
            pipeline_metadata=PipelineMetadata(query_id=query_context.query_id),
        )

    async def stream(
        self,
        query_context: QueryContext,
        retrieved_context: RetrievedContext,
    ) -> AsyncGenerator[StreamingChunk, None]:
        messages = self._build_messages(query_context, retrieved_context)

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True,
            )
        except Exception as exc:
            raise GenerationAPIError(f"OpenAI stream failed: {exc}") from exc

        full_text = ""
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_text += delta
                yield StreamingChunk(
                    event="token",
                    data={"text": delta, "query_id": query_context.query_id},
                )

        citations = self._extract_citations(full_text, retrieved_context)
        yield StreamingChunk(
            event="citation",
            data={
                "citations": [self._citation_to_dict(c) for c in citations],
                "query_id": query_context.query_id,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        query_context: QueryContext,
        retrieved_context: RetrievedContext,
    ) -> list[dict]:
        if not retrieved_context.chunks:
            user_content = (
                f"{NO_CONTEXT_RESPONSE}\n\nQuestion: {query_context.standalone_query}"
            )
            return [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]

        # Build context block — drop lowest-scored chunks if too long
        chunks_data = [
            {
                "rank": sc.rank,
                "document_name": sc.chunk.document_name,
                "page_numbers": sc.chunk.page_numbers,
                "chunk_index": sc.chunk.chunk_index,
                "text": sc.chunk.text,
            }
            for sc in retrieved_context.chunks
        ]

        context_block = build_context_block(chunks_data)
        while (
            count_tokens(context_block) > self._max_context_tokens
            and len(chunks_data) > 1
        ):
            chunks_data.pop()  # remove last (lowest ranked)
            context_block = build_context_block(chunks_data)

        context_section = CONTEXT_TEMPLATE.format(context_block=context_block)

        user_parts = [context_section]
        if query_context.formatted_history:
            user_parts.append(f"Conversation history:\n{query_context.formatted_history}")
        user_parts.append(f"Question: {query_context.standalone_query}")

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

    @staticmethod
    def _extract_citations(
        answer_text: str,
        retrieved_context: RetrievedContext,
    ) -> list[Citation]:
        # Find all [Source N] references
        refs = set(int(m) for m in re.findall(r"\[Source (\d+)\]", answer_text))
        citations: list[Citation] = []

        chunk_by_rank = {sc.rank: sc for sc in retrieved_context.chunks}
        for rank in sorted(refs):
            sc = chunk_by_rank.get(rank)
            if sc is None:
                continue  # hallucinated source number
            excerpt = sc.chunk.text[:200].replace("\n", " ").strip()
            citations.append(Citation(
                document_name=sc.chunk.document_name,
                page_numbers=sc.chunk.page_numbers,
                chunk_index=sc.chunk.chunk_index,
                chunk_id=sc.chunk.chunk_id,
                excerpt=excerpt,
            ))
        return citations

    @staticmethod
    def _compute_confidence(
        answer_text: str,
        retrieved_context: RetrievedContext,
        citations: list[Citation],
    ) -> float:
        if not retrieved_context.chunks:
            return 0.0

        mean_score = sum(sc.similarity_score for sc in retrieved_context.chunks) / len(
            retrieved_context.chunks
        )

        # Normalize cosine similarity to [0, 1] against realistic bounds for
        # text-embedding-3-small (related text scores 0.10–0.55; raw scores used
        # directly as a multiplier would permanently cap confidence below ~0.35).
        _SCORE_MIN = 0.10
        _SCORE_MAX = 0.55
        normalized = max(0.0, min(1.0, (mean_score - _SCORE_MIN) / (_SCORE_MAX - _SCORE_MIN)))

        # Citation density factor
        citation_factor = min(1.0, len(citations) / max(len(retrieved_context.chunks), 1))

        # Uncertainty penalty
        uncertainty_phrases = ["i don't know", "i cannot", "not in the document", "no information"]
        penalty = 0.85 if any(p in answer_text.lower() for p in uncertainty_phrases) else 1.0

        return round(min(1.0, normalized * (0.7 + 0.3 * citation_factor) * penalty), 3)

    @staticmethod
    def _citation_to_dict(c: Citation) -> dict:
        return {
            "document_name": c.document_name,
            "page_numbers": c.page_numbers,
            "chunk_index": c.chunk_index,
            "chunk_id": c.chunk_id,
            "excerpt": c.excerpt,
        }
