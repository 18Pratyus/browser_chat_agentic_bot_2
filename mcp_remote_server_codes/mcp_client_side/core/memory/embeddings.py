"""
Embedding Functions for Semantic Memory
=======================================
Provides embedding functions for semantic search in memory store.

Supports:
- OpenAI embeddings
- Ollama local embeddings
- Sentence Transformers (local)
- Mock embeddings for testing
"""

from typing import List, Optional
from abc import ABC, abstractmethod
import hashlib
import numpy as np


class BaseEmbeddingFunction(ABC):
    """Base class for embedding functions."""

    @abstractmethod
    async def __call__(self, text: str) -> List[float]:
        """Generate embedding for text."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        pass


class OllamaEmbeddings(BaseEmbeddingFunction):
    """
    Ollama-based embeddings using local models.

    Uses nomic-embed-text or similar embedding model.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
    ):
        self.base_url = base_url
        self.model = model

    async def __call__(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data["embedding"]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        embeddings = []
        for text in texts:
            emb = await self(text)
            embeddings.append(emb)
        return embeddings


class OpenAIEmbeddings(BaseEmbeddingFunction):
    """
    OpenAI-based embeddings.

    Uses text-embedding-3-small or similar model.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
    ):
        self.api_key = api_key
        self.model = model

    async def __call__(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": text},
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]


class SentenceTransformerEmbeddings(BaseEmbeddingFunction):
    """
    Local embeddings using Sentence Transformers.

    Uses all-MiniLM-L6-v2 or similar model.
    Runs entirely locally, no API calls.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        """Lazy load the model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    async def __call__(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        import asyncio

        model = self._get_model()
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None,
            lambda: model.encode(text).tolist()
        )
        return embedding

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        import asyncio

        model = self._get_model()
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: model.encode(texts).tolist()
        )
        return embeddings


class MockEmbeddings(BaseEmbeddingFunction):
    """
    Mock embeddings for testing.

    Generates deterministic embeddings based on text hash.
    """

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    async def __call__(self, text: str) -> List[float]:
        """Generate mock embedding."""
        # Create deterministic embedding from text hash
        hash_bytes = hashlib.sha256(text.encode()).digest()

        # Convert to floats
        embedding = []
        for i in range(self.dimensions):
            byte_idx = i % len(hash_bytes)
            value = (hash_bytes[byte_idx] - 128) / 128.0  # Normalize to [-1, 1]
            embedding.append(value)

        # Normalize the vector
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = [x / norm for x in embedding]

        return embedding

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate mock embeddings for multiple texts."""
        return [await self(text) for text in texts]


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = np.sqrt(sum(a * a for a in vec1))
    norm2 = np.sqrt(sum(b * b for b in vec2))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


# Factory function
def get_embedding_function(
    provider: str = "mock",
    **kwargs
) -> BaseEmbeddingFunction:
    """
    Get an embedding function based on provider.

    Args:
        provider: One of "ollama", "openai", "sentence_transformer", "mock"
        **kwargs: Provider-specific arguments

    Returns:
        Embedding function instance
    """
    providers = {
        "ollama": OllamaEmbeddings,
        "openai": OpenAIEmbeddings,
        "sentence_transformer": SentenceTransformerEmbeddings,
        "mock": MockEmbeddings,
    }

    if provider not in providers:
        raise ValueError(f"Unknown provider: {provider}. Available: {list(providers.keys())}")

    return providers[provider](**kwargs)
