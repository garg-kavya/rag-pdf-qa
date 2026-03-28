"""Shared AsyncOpenAI client factory with LangSmith instrumentation.

When LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY are set, every
OpenAI call (completions, embeddings, reformulation, compression) is
automatically traced in LangSmith — token counts, cost, latency, full
prompt/response — with zero changes to the call sites.

Without the env vars the client connects directly to OpenAI.
"""
from __future__ import annotations

import os

from openai import AsyncOpenAI

from app.config import Settings


def make_openai_client(settings: Settings) -> AsyncOpenAI:
    """Return an AsyncOpenAI client, optionally instrumented via LangSmith."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true":
        from langsmith.wrappers import wrap_openai
        client = wrap_openai(client)
    return client
