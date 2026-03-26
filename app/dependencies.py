"""FastAPI Dependency Injection — composition root."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError

from app.auth.jwt_handler import decode_access_token, oauth2_scheme
from app.cache.embedding_cache import EmbeddingCache
from app.cache.in_memory_cache import InMemoryCache
from app.cache.response_cache import ResponseCache
from app.chains.rag_chain import RAGChain
from app.config import Settings, get_settings
from app.db.document_registry import DocumentRegistry
from app.db.session_store import SessionStore
from app.db.user_store import UserStore
from app.db.vector_store import VectorStore
from app.memory.context_builder import ContextBuilder
from app.memory.memory_compressor import MemoryCompressor
from app.memory.memory_manager import MemoryManager
from app.models.user import User
from app.pipeline.ingestion_pipeline import IngestionPipeline
from app.pipeline.rag_pipeline import RAGPipeline
from app.services.chunker import ChunkerService
from app.services.embedder import EmbedderService
from app.services.pdf_processor import PDFProcessorService
from app.services.query_reformulator import QueryReformulator
from app.services.reranker import RerankerService
from app.services.retriever import RetrieverService
from app.services.streaming import StreamingHandler
from app.services.text_cleaner import TextCleanerService


def build_app_state(settings: Settings) -> dict:
    """Construct the full object graph at startup. Returns a dict for app.state."""
    # Storage
    if settings.vector_store_type == "chroma":
        from app.db.chroma_store import ChromaStore
        vector_store: VectorStore = ChromaStore(
            persist_path=f"{settings.vector_store_path}/chroma"
        )
    else:
        from app.db.faiss_store import FAISSStore
        vector_store = FAISSStore(
            dimensions=settings.embedding_dimensions,
            persist_path=f"{settings.vector_store_path}/faiss",
        )

    _data_dir = settings.vector_store_path  # e.g. "./data"
    session_store = SessionStore(settings, persist_path=f"{_data_dir}/sessions.json")
    document_registry = DocumentRegistry(persist_path=f"{_data_dir}/registry.json")
    user_store = UserStore(db_path=f"{_data_dir}/users.db")

    # Cache
    shared_cache = InMemoryCache(
        max_size=settings.cache_max_size,
        default_ttl=settings.embedding_cache_ttl_seconds,
    )

    # Services
    embedder = EmbedderService(settings)
    embedding_cache = EmbeddingCache(
        backend=shared_cache,
        embedder=embedder,
        ttl=settings.embedding_cache_ttl_seconds,
    )

    response_cache_backend = InMemoryCache(
        max_size=settings.cache_max_size,
        default_ttl=settings.response_cache_ttl_seconds,
    )
    response_cache = ResponseCache(
        backend=response_cache_backend,
        ttl=settings.response_cache_ttl_seconds,
    )

    retriever = RetrieverService(vector_store, settings)
    reranker = RerankerService(settings)
    reformulator = QueryReformulator(settings)

    # Memory
    context_builder = ContextBuilder()
    compressor = MemoryCompressor(settings)
    memory_manager = MemoryManager(session_store, context_builder, compressor)

    # Chain
    rag_chain = RAGChain(settings)

    # Pipelines
    rag_pipeline = RAGPipeline(
        session_store=session_store,
        response_cache=response_cache,
        embedding_cache=embedding_cache,
        reformulator=reformulator,
        retriever=retriever,
        reranker=reranker,
        memory_manager=memory_manager,
        rag_chain=rag_chain,
        settings=settings,
    )

    pdf_processor = PDFProcessorService()
    text_cleaner = TextCleanerService()
    chunker = ChunkerService(settings)

    ingestion_pipeline = IngestionPipeline(
        pdf_processor=pdf_processor,
        text_cleaner=text_cleaner,
        chunker=chunker,
        embedder=embedder,
        vector_store=vector_store,
        document_registry=document_registry,
        session_store=session_store,
        embedding_model=settings.embedding_model,
    )

    return {
        "settings": settings,
        "vector_store": vector_store,
        "session_store": session_store,
        "document_registry": document_registry,
        "user_store": user_store,
        "embedding_cache": embedding_cache,
        "response_cache": response_cache,
        "rag_pipeline": rag_pipeline,
        "ingestion_pipeline": ingestion_pipeline,
    }


# ---------------------------------------------------------------------------
# FastAPI Depends functions (read from request.app.state)
# ---------------------------------------------------------------------------

def get_settings(request: Request) -> Settings:  # type: ignore[override]
    return request.app.state.settings


def get_rag_pipeline(request: Request) -> RAGPipeline:
    return request.app.state.rag_pipeline


def get_ingestion_pipeline(request: Request) -> IngestionPipeline:
    return request.app.state.ingestion_pipeline


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


def get_document_registry(request: Request) -> DocumentRegistry:
    return request.app.state.document_registry


def get_vector_store(request: Request) -> VectorStore:
    return request.app.state.vector_store


def get_response_cache(request: Request) -> ResponseCache:
    return request.app.state.response_cache


def get_user_store(request: Request) -> UserStore:
    return request.app.state.user_store


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user_store: UserStore = request.app.state.user_store
    user = await user_store.get_by_id(user_id)
    if user is None:
        raise credentials_exception
    return user
