"""
MongoDB Long-Term Memory Store
==============================
Cross-session memory: Stores user preferences, learned patterns, skills.
Persists across conversations and threads.

Features:
- Namespace-based organization (user_prefs, skills, facts, etc.)
- Semantic search via embeddings
- TTL support for temporary memories
- Metadata filtering
"""

from typing import Any, Optional, List, Dict, AsyncIterator
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import json
import hashlib

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


@dataclass
class MemoryItem:
    """A single memory item."""
    key: str
    value: Dict[str, Any]
    namespace: tuple
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None


class MongoDBMemoryStore:
    """
    MongoDB-based long-term memory store for LangGraph.

    Supports:
    - Namespaced memory (e.g., ("user", "preferences"), ("skills", "learned"))
    - Semantic search via vector embeddings
    - Cross-session persistence
    - Memory lifecycle management (TTL)

    Collections:
    - memories: Main memory storage
    - memory_embeddings: Vector embeddings for semantic search
    """

    def __init__(
        self,
        connection_string: str = "mongodb://localhost:27017",
        database_name: str = "agentic_bot",
        collection_name: str = "memories",
        embedding_function: Optional[callable] = None,
    ):
        self.client = AsyncIOMotorClient(connection_string)
        self.db: AsyncIOMotorDatabase = self.client[database_name]
        self.collection = self.db[collection_name]
        self.embedding_fn = embedding_function

    async def setup(self) -> None:
        """Create indexes for efficient queries."""
        # Compound index for namespace + key
        await self.collection.create_index([
            ("namespace", 1),
            ("key", 1)
        ], unique=True)

        # Index for TTL (auto-delete expired memories)
        await self.collection.create_index(
            "expires_at",
            expireAfterSeconds=0
        )

        # Index for metadata queries
        await self.collection.create_index([
            ("namespace", 1),
            ("metadata.type", 1)
        ])

        # Index for recent memories
        await self.collection.create_index([
            ("namespace", 1),
            ("updated_at", -1)
        ])

        print(f"[MemoryStore] MongoDB indexes created on {self.collection.name}")

    def _namespace_to_str(self, namespace: tuple) -> str:
        """Convert namespace tuple to string for storage."""
        return "/".join(namespace)

    def _str_to_namespace(self, namespace_str: str) -> tuple:
        """Convert namespace string back to tuple."""
        return tuple(namespace_str.split("/"))

    def _generate_key(self, namespace: tuple, key: str) -> str:
        """Generate a unique key for the memory item."""
        namespace_str = self._namespace_to_str(namespace)
        return hashlib.sha256(f"{namespace_str}:{key}".encode()).hexdigest()[:16]

    async def aput(
        self,
        namespace: tuple,
        key: str,
        value: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        Store a memory item.

        Args:
            namespace: Tuple like ("user", "preferences") or ("skills", "learned")
            key: Unique key within the namespace
            value: The data to store
            metadata: Optional metadata for filtering
            ttl_seconds: Optional TTL for auto-expiration
        """
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None

        # Generate embedding if function provided and value has text
        embedding = None
        if self.embedding_fn and isinstance(value, dict):
            text_content = value.get("text") or value.get("description") or str(value)
            if text_content:
                embedding = await self.embedding_fn(text_content)

        doc = {
            "namespace": self._namespace_to_str(namespace),
            "key": key,
            "value": value,
            "metadata": metadata or {},
            "embedding": embedding,
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
        }

        await self.collection.update_one(
            {"namespace": doc["namespace"], "key": key},
            {"$set": doc},
            upsert=True
        )

    async def agent(
        self,
        namespace: tuple,
        key: str
    ) -> Optional[MemoryItem]:
        """Get a specific memory item."""
        doc = await self.collection.find_one({
            "namespace": self._namespace_to_str(namespace),
            "key": key
        })

        if not doc:
            return None

        return MemoryItem(
            key=doc["key"],
            value=doc["value"],
            namespace=self._str_to_namespace(doc["namespace"]),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            expires_at=doc.get("expires_at"),
            metadata=doc.get("metadata", {}),
            embedding=doc.get("embedding"),
        )

    async def adelete(self, namespace: tuple, key: str) -> bool:
        """Delete a memory item."""
        result = await self.collection.delete_one({
            "namespace": self._namespace_to_str(namespace),
            "key": key
        })
        return result.deleted_count > 0

    async def alist(
        self,
        namespace: tuple,
        limit: int = 100,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """List all memories in a namespace."""
        query = {"namespace": self._namespace_to_str(namespace)}

        if metadata_filter:
            for k, v in metadata_filter.items():
                query[f"metadata.{k}"] = v

        cursor = self.collection.find(query).sort("updated_at", -1).limit(limit)

        items = []
        async for doc in cursor:
            items.append(MemoryItem(
                key=doc["key"],
                value=doc["value"],
                namespace=self._str_to_namespace(doc["namespace"]),
                created_at=doc["created_at"],
                updated_at=doc["updated_at"],
                expires_at=doc.get("expires_at"),
                metadata=doc.get("metadata", {}),
                embedding=doc.get("embedding"),
            ))

        return items

    async def asearch(
        self,
        namespace: tuple,
        query: str,
        limit: int = 5,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """
        Semantic search within a namespace.

        Uses vector similarity if embeddings are available,
        otherwise falls back to text search.
        """
        if not self.embedding_fn:
            # Fallback to text search
            return await self._text_search(namespace, query, limit, metadata_filter)

        # Get query embedding
        query_embedding = await self.embedding_fn(query)

        # Build aggregation pipeline for vector search
        match_query = {"namespace": self._namespace_to_str(namespace)}
        if metadata_filter:
            for k, v in metadata_filter.items():
                match_query[f"metadata.{k}"] = v

        # Simple cosine similarity calculation
        # Note: For production, use MongoDB Atlas Vector Search
        pipeline = [
            {"$match": match_query},
            {"$match": {"embedding": {"$exists": True, "$ne": None}}},
            {
                "$addFields": {
                    "similarity": {
                        "$let": {
                            "vars": {
                                "dotProduct": {
                                    "$reduce": {
                                        "input": {"$range": [0, {"$size": "$embedding"}]},
                                        "initialValue": 0,
                                        "in": {
                                            "$add": [
                                                "$$value",
                                                {
                                                    "$multiply": [
                                                        {"$arrayElemAt": ["$embedding", "$$this"]},
                                                        {"$arrayElemAt": [query_embedding, "$$this"]}
                                                    ]
                                                }
                                            ]
                                        }
                                    }
                                }
                            },
                            "in": "$$dotProduct"
                        }
                    }
                }
            },
            {"$sort": {"similarity": -1}},
            {"$limit": limit}
        ]

        cursor = self.collection.aggregate(pipeline)

        items = []
        async for doc in cursor:
            items.append(MemoryItem(
                key=doc["key"],
                value=doc["value"],
                namespace=self._str_to_namespace(doc["namespace"]),
                created_at=doc["created_at"],
                updated_at=doc["updated_at"],
                metadata=doc.get("metadata", {}),
                embedding=doc.get("embedding"),
            ))

        return items

    async def _text_search(
        self,
        namespace: tuple,
        query: str,
        limit: int,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """Fallback text search using regex."""
        match_query = {
            "namespace": self._namespace_to_str(namespace),
            "$or": [
                {"key": {"$regex": query, "$options": "i"}},
                {"value": {"$regex": query, "$options": "i"}},
            ]
        }

        if metadata_filter:
            for k, v in metadata_filter.items():
                match_query[f"metadata.{k}"] = v

        cursor = self.collection.find(match_query).limit(limit)

        items = []
        async for doc in cursor:
            items.append(MemoryItem(
                key=doc["key"],
                value=doc["value"],
                namespace=self._str_to_namespace(doc["namespace"]),
                created_at=doc["created_at"],
                updated_at=doc["updated_at"],
                metadata=doc.get("metadata", {}),
            ))

        return items

    async def clear_namespace(self, namespace: tuple) -> int:
        """Delete all memories in a namespace."""
        result = await self.collection.delete_many({
            "namespace": self._namespace_to_str(namespace)
        })
        return result.deleted_count

    async def get_namespaces(self) -> List[str]:
        """Get all unique namespaces."""
        namespaces = await self.collection.distinct("namespace")
        return namespaces

    async def get_stats(self) -> Dict[str, Any]:
        """Get memory store statistics."""
        total_count = await self.collection.count_documents({})

        # Count by namespace
        pipeline = [
            {"$group": {"_id": "$namespace", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        namespace_counts = {}
        async for doc in self.collection.aggregate(pipeline):
            namespace_counts[doc["_id"]] = doc["count"]

        return {
            "total_memories": total_count,
            "by_namespace": namespace_counts,
        }


# Predefined namespaces
class MemoryNamespaces:
    """Standard memory namespaces."""
    USER_PREFERENCES = ("user", "preferences")
    USER_FACTS = ("user", "facts")
    CONVERSATION_CONTEXT = ("conversation", "context")
    LEARNED_SKILLS = ("skills", "learned")
    SYNTHESIZED_SKILLS = ("skills", "synthesized")
    TOOL_PATTERNS = ("tools", "patterns")
    ERROR_LESSONS = ("errors", "lessons")
    WORKFLOW_HISTORY = ("workflows", "history")


# Singleton instance
_store: Optional[MongoDBMemoryStore] = None


async def get_memory_store(
    connection_string: str = "mongodb://localhost:27017",
    database_name: str = "First_mongoDB_database",
    embedding_function: Optional[callable] = None,
) -> MongoDBMemoryStore:
    """Get or create the MongoDB memory store instance."""
    global _store

    if _store is None:
        _store = MongoDBMemoryStore(
            connection_string=connection_string,
            database_name=database_name,
            collection_name="long_term_memories",
            embedding_function=embedding_function,
        )
        await _store.setup()
        print(f"[MemoryStore] Connected to MongoDB: {database_name}")

    return _store
