"""Centralized prompt templates."""
from __future__ import annotations

SYSTEM_PROMPT = """\
You are a document analyst. Answer questions using the provided source documents.

Rules:
- Ground every factual claim in the provided context and cite it with [Source N].
- You MAY draw reasonable inferences from the evidence in the context — for \
example, inferring character, suitability, or intent from facts present in the \
documents. Clearly label inferences as your interpretation (e.g. "Based on the \
evidence, it appears…").
- Do NOT invent facts that are absent from the context.
- If there is genuinely no relevant information at all, say: \
"I could not find relevant information in the uploaded documents."
- Be concise. Prefer direct answers over lengthy preamble.
- When a user requests tabular output, or when the data you are presenting is \
naturally structured (comparisons, lists of attributes, multi-column data), \
format it as a Markdown table using pipe syntax."""

CONTEXT_TEMPLATE = """\
Source Documents:
{context_block}"""

NO_CONTEXT_RESPONSE = (
    "I could not find relevant information in the uploaded documents "
    "to answer your question. Please try rephrasing or ensure the "
    "relevant document has been uploaded."
)

QUERY_REFORMULATION_PROMPT = """\
Given the conversation history below and a follow-up question, rewrite the \
follow-up into a self-contained standalone question that includes all necessary \
context from the history. Do NOT answer — only reformulate.

Conversation history:
{history}

Follow-up question: {question}

Standalone question:"""


def build_context_block(chunks: list[dict]) -> str:
    """Format retrieved chunks into a numbered source block."""
    parts = []
    for chunk in chunks:
        header = (
            f"[Source {chunk['rank']}] "
            f"({chunk['document_name']}, "
            f"Page {chunk['page_numbers']}, "
            f"Chunk {chunk['chunk_index']})"
        )
        parts.append(f"{header}\n{chunk['text']}")
    return "\n\n".join(parts)
