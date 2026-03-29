"""Query Router — classifies user queries to route between RAG and calculator."""
from __future__ import annotations

from typing import Literal

from app.config import Settings
from app.utils.logging import get_logger
from app.utils.openai_client import make_openai_client

logger = get_logger(__name__)

_CLASSIFY_PROMPT = """\
Classify this user query as either "rag" or "calculator".

"calculator" — the question requires precise mathematical computation; \
the answer is a specific number.
Examples: sum of revenues, total expenses, average salary, percentage growth, \
how many items, difference between two values.

"rag" — everything else: explanations, definitions, comparisons, descriptions, \
yes/no questions, strategy questions.
Examples: what is the company strategy, explain the risk factors, who is the CEO.

Query: {query}

Reply with exactly one word — rag or calculator."""

_CODEGEN_PROMPT = """\
You are a precise Python programmer. The user asked:
"{query}"

Here are the relevant document excerpts that contain the data:
---
{context}
---

Write a Python script that:
1. Assigns a variable for every number extracted from the excerpts above
2. Performs the exact calculation the user asked for
3. Prints the final answer with a clear label
   e.g.: print("Total Q3 Revenue: $4,521,000")

Rules:
- Extract numbers EXACTLY as they appear in the text
- NO import statements (the math module is already available as `math`)
- Comment each step so the work is auditable
- The last statement must be print(...)

Return ONLY valid Python code. No markdown fences, no explanation."""


class QueryRouter:

    def __init__(self, settings: Settings) -> None:
        self._client = make_openai_client(settings)
        self._llm_model = settings.llm_model

    async def classify(self, query: str) -> Literal["rag", "calculator"]:
        """Return 'rag' or 'calculator'. Defaults to 'rag' on any failure."""
        try:
            resp = await self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(query=query)}],
                max_tokens=5,
                temperature=0.0,
            )
            label = resp.choices[0].message.content.strip().lower()
            if "calculator" in label:
                logger.debug("Router → calculator: %r", query[:80])
                return "calculator"
        except Exception as exc:
            logger.warning("Router classification failed, defaulting to rag: %s", exc)
        return "rag"

    async def generate_code(self, query: str, context_text: str) -> str:
        """Ask the LLM to write sandboxed Python to answer a math query."""
        resp = await self._client.chat.completions.create(
            model=self._llm_model,
            messages=[
                {
                    "role": "user",
                    "content": _CODEGEN_PROMPT.format(query=query, context=context_text),
                }
            ],
            max_tokens=512,
            temperature=0.0,
        )
        return resp.choices[0].message.content.strip()
