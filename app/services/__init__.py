"""
Service Layer
==============

Business logic services that implement the RAG pipeline stages:

    PDF Processing:
        pdf_processor  -> Parse raw PDF bytes into structured page text
        text_cleaner   -> Normalize and clean extracted text
        chunker        -> Split clean text into retrieval-optimized chunks

    Embedding & Retrieval:
        embedder       -> Generate vector embeddings via OpenAI API
        retriever      -> Semantic search + MMR re-ranking

    Generation:
        query_reformulator -> Resolve conversational follow-ups into standalone queries
        generator          -> LLM-powered answer generation with citation awareness

    Reranking:
        reranker       -> Cross-encoder / Cohere second-pass relevance reranker

    Streaming:
        streaming      -> Server-Sent Events token streaming handler

Each service is stateless and receives its dependencies via constructor injection.
Services are instantiated once at app startup and shared across requests.
"""
