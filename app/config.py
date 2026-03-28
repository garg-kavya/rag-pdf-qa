"""Application configuration via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_name: str = "DocMind"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 50
    vector_store_path: str = "./data"

    # --- OpenAI ---
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 100
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1024

    # --- Chunking ---
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    split_separators: list[str] = ["\n\n", "\n", ". ", " "]

    # --- Retrieval ---
    vector_store_type: Literal["faiss", "chroma"] = "chroma"
    top_k: int = 10
    top_k_candidates: int = 20
    similarity_threshold: float = 0.0
    mmr_diversity_factor: float = 0.7

    # --- Reranker ---
    reranker_backend: Literal["none", "cross_encoder", "cohere"] = "none"
    cohere_api_key: str | None = None
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- Cache ---
    cache_backend: str = "memory"
    cache_max_size: int = 1000
    embedding_cache_ttl_seconds: int = 86400
    response_cache_ttl_seconds: int = 60

    # --- Memory ---
    memory_token_budget: int = 1024
    compression_threshold: int = 10
    compression_turns: int = 5

    # --- Sessions ---
    # 0 = never expire (ChatGPT-style persistent conversations)
    session_ttl_minutes: int = 0
    max_conversation_turns: int = 100
    session_cleanup_interval_seconds: int = 300

    # --- Database ---
    database_url: str = "postgresql://docmind:docmind@localhost:5432/docmind"

    # --- Auth ---
    jwt_secret_key: str = "change-me-in-production-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24 * 365  # 1 year

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    cors_origins: list[str] = ["*"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v  # type: ignore[return-value]

    @field_validator("split_separators", mode="before")
    @classmethod
    def parse_separators(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return v.split(",")
        return v  # type: ignore[return-value]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
