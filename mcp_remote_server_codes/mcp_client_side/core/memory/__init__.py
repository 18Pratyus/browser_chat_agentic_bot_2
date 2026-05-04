"""
Memory Module
=============
Provides short-term and long-term memory for the agentic bot.

Components:
- checkpointer: MongoDB-based checkpoint storage (conversation state)
- store: MongoDB-based long-term memory (cross-session)
- embeddings: Embedding functions for semantic search
- manager: Unified interface for all memory operations
"""

from .checkpointer import MongoDBCheckpointer, get_checkpointer
from .store import MongoDBMemoryStore, MemoryNamespaces, MemoryItem, get_memory_store
from .embeddings import (
    BaseEmbeddingFunction,
    OllamaEmbeddings,
    OpenAIEmbeddings,
    SentenceTransformerEmbeddings,
    MockEmbeddings,
    get_embedding_function,
    cosine_similarity,
)
from .manager import MemoryManager, get_memory_manager

__all__ = [
    # Checkpointer
    "MongoDBCheckpointer",
    "get_checkpointer",
    # Store
    "MongoDBMemoryStore",
    "MemoryNamespaces",
    "MemoryItem",
    "get_memory_store",
    # Embeddings
    "BaseEmbeddingFunction",
    "OllamaEmbeddings",
    "OpenAIEmbeddings",
    "SentenceTransformerEmbeddings",
    "MockEmbeddings",
    "get_embedding_function",
    "cosine_similarity",
    # Manager
    "MemoryManager",
    "get_memory_manager",
]
