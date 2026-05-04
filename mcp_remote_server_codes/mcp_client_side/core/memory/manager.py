"""
Unified Memory Manager
======================
Single interface for all memory operations.

Combines:
- Short-term memory (checkpointer) - conversation state
- Long-term memory (store) - cross-session data
- Semantic search capabilities
"""

from typing import Any, Dict, List, Optional
from datetime import datetime

from .checkpointer import MongoDBCheckpointer, get_checkpointer
from .store import MongoDBMemoryStore, MemoryNamespaces, MemoryItem, get_memory_store
from .embeddings import get_embedding_function, BaseEmbeddingFunction


class MemoryManager:
    """
    Unified memory manager for the agentic bot.

    Provides a single interface for:
    - Conversation state (short-term)
    - User preferences and facts (long-term)
    - Learned skills and patterns
    - Semantic search across memories
    """

    def __init__(
        self,
        checkpointer: MongoDBCheckpointer,
        store: MongoDBMemoryStore,
    ):
        self.checkpointer = checkpointer
        self.store = store

    # ══════════════════════════════════════════════════════════════
    # SHORT-TERM MEMORY (Conversation State)
    # ══════════════════════════════════════════════════════════════

    async def get_conversation_state(self, thread_id: str) -> Optional[Dict]:
        """Get the current state of a conversation."""
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await self.checkpointer.aget_tuple(config)

        if checkpoint_tuple:
            return checkpoint_tuple.checkpoint
        return None

    async def get_conversation_history(
        self,
        thread_id: str,
        limit: int = 50
    ) -> List[Dict]:
        """Get checkpoint history for time travel UI."""
        return await self.checkpointer.get_thread_history(thread_id, limit)

    async def delete_conversation(self, thread_id: str) -> None:
        """Delete a conversation and all its checkpoints."""
        await self.checkpointer.adelete_thread(thread_id)

    # ══════════════════════════════════════════════════════════════
    # LONG-TERM MEMORY (Cross-Session)
    # ══════════════════════════════════════════════════════════════

    # User Preferences
    async def save_user_preference(
        self,
        user_id: str,
        key: str,
        value: Any,
        category: str = "general"
    ) -> None:
        """Save a user preference."""
        await self.store.aput(
            namespace=MemoryNamespaces.USER_PREFERENCES,
            key=f"{user_id}:{key}",
            value={"value": value, "category": category, "user_id": user_id},
            metadata={"user_id": user_id, "category": category}
        )

    async def get_user_preference(
        self,
        user_id: str,
        key: str
    ) -> Optional[Any]:
        """Get a user preference."""
        item = await self.store.aget(
            namespace=MemoryNamespaces.USER_PREFERENCES,
            key=f"{user_id}:{key}"
        )
        return item.value.get("value") if item else None

    async def get_all_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get all preferences for a user."""
        items = await self.store.alist(
            namespace=MemoryNamespaces.USER_PREFERENCES,
            metadata_filter={"user_id": user_id}
        )
        return {item.key.split(":")[-1]: item.value.get("value") for item in items}

    # User Facts (learned about user)
    async def remember_fact(
        self,
        user_id: str,
        fact: str,
        source: str = "conversation"
    ) -> None:
        """Remember a fact about the user."""
        fact_key = f"{user_id}:{hash(fact) % 10000}"
        await self.store.aput(
            namespace=MemoryNamespaces.USER_FACTS,
            key=fact_key,
            value={
                "fact": fact,
                "user_id": user_id,
                "source": source,
                "learned_at": datetime.utcnow().isoformat()
            },
            metadata={"user_id": user_id, "source": source}
        )

    async def recall_facts(
        self,
        user_id: str,
        query: Optional[str] = None,
        limit: int = 10
    ) -> List[str]:
        """Recall facts about the user, optionally filtered by query."""
        if query:
            items = await self.store.asearch(
                namespace=MemoryNamespaces.USER_FACTS,
                query=query,
                limit=limit,
                metadata_filter={"user_id": user_id}
            )
        else:
            items = await self.store.alist(
                namespace=MemoryNamespaces.USER_FACTS,
                limit=limit,
                metadata_filter={"user_id": user_id}
            )
        return [item.value.get("fact") for item in items]

    # ══════════════════════════════════════════════════════════════
    # SKILL MEMORY
    # ══════════════════════════════════════════════════════════════

    async def save_skill(
        self,
        skill_id: str,
        skill_data: Dict[str, Any]
    ) -> None:
        """Save a learned skill."""
        await self.store.aput(
            namespace=MemoryNamespaces.LEARNED_SKILLS,
            key=skill_id,
            value=skill_data,
            metadata={
                "name": skill_data.get("name"),
                "type": "learned"
            }
        )

    async def get_skill(self, skill_id: str) -> Optional[Dict]:
        """Get a skill by ID."""
        item = await self.store.aget(
            namespace=MemoryNamespaces.LEARNED_SKILLS,
            key=skill_id
        )
        return item.value if item else None

    async def search_skills(
        self,
        query: str,
        limit: int = 5
    ) -> List[Dict]:
        """Search for skills by semantic similarity."""
        items = await self.store.asearch(
            namespace=MemoryNamespaces.LEARNED_SKILLS,
            query=query,
            limit=limit
        )
        return [item.value for item in items]

    async def list_all_skills(self, limit: int = 100) -> List[Dict]:
        """List all learned skills."""
        items = await self.store.alist(
            namespace=MemoryNamespaces.LEARNED_SKILLS,
            limit=limit
        )
        return [item.value for item in items]

    # ══════════════════════════════════════════════════════════════
    # ERROR LEARNING
    # ══════════════════════════════════════════════════════════════

    async def save_error_lesson(
        self,
        error_type: str,
        lesson: Dict[str, Any]
    ) -> None:
        """Save a lesson learned from an error."""
        lesson_key = f"{error_type}:{hash(str(lesson)) % 10000}"
        await self.store.aput(
            namespace=MemoryNamespaces.ERROR_LESSONS,
            key=lesson_key,
            value={
                **lesson,
                "error_type": error_type,
                "learned_at": datetime.utcnow().isoformat()
            },
            metadata={"error_type": error_type}
        )

    async def get_error_lessons(
        self,
        error_type: str,
        limit: int = 5
    ) -> List[Dict]:
        """Get lessons for a specific error type."""
        items = await self.store.alist(
            namespace=MemoryNamespaces.ERROR_LESSONS,
            limit=limit,
            metadata_filter={"error_type": error_type}
        )
        return [item.value for item in items]

    # ══════════════════════════════════════════════════════════════
    # WORKFLOW HISTORY
    # ══════════════════════════════════════════════════════════════

    async def save_workflow(
        self,
        workflow_id: str,
        workflow_data: Dict[str, Any]
    ) -> None:
        """Save a workflow execution for pattern analysis."""
        await self.store.aput(
            namespace=MemoryNamespaces.WORKFLOW_HISTORY,
            key=workflow_id,
            value={
                **workflow_data,
                "executed_at": datetime.utcnow().isoformat()
            },
            metadata={
                "success": workflow_data.get("success", False),
                "tools_used": workflow_data.get("tools_used", [])
            }
        )

    async def get_recent_workflows(
        self,
        limit: int = 50,
        successful_only: bool = False
    ) -> List[Dict]:
        """Get recent workflow executions."""
        metadata_filter = {"success": True} if successful_only else None
        items = await self.store.alist(
            namespace=MemoryNamespaces.WORKFLOW_HISTORY,
            limit=limit,
            metadata_filter=metadata_filter
        )
        return [item.value for item in items]

    # ══════════════════════════════════════════════════════════════
    # STATISTICS
    # ══════════════════════════════════════════════════════════════

    async def get_memory_stats(self) -> Dict[str, Any]:
        """Get overall memory statistics."""
        store_stats = await self.store.get_stats()
        return {
            "long_term": store_stats,
            "namespaces": await self.store.get_namespaces()
        }


# ══════════════════════════════════════════════════════════════════
# Factory Function
# ══════════════════════════════════════════════════════════════════

_memory_manager: Optional[MemoryManager] = None


async def get_memory_manager(
    connection_string: str = "mongodb://localhost:27017",
    database_name: str = "First_mongoDB_database",
    embedding_provider: str = "mock"
) -> MemoryManager:
    """
    Get or create the memory manager instance.

    Args:
        connection_string: MongoDB connection string
        database_name: Database name
        embedding_provider: One of "mock", "ollama", "openai", "sentence_transformer"

    Returns:
        MemoryManager instance
    """
    global _memory_manager

    if _memory_manager is None:
        # Get embedding function
        embedding_fn = get_embedding_function(embedding_provider)

        # Initialize checkpointer and store
        checkpointer = await get_checkpointer(connection_string, database_name)
        store = await get_memory_store(connection_string, database_name, embedding_fn)

        _memory_manager = MemoryManager(checkpointer, store)
        print(f"[MemoryManager] Initialized with {embedding_provider} embeddings")

    return _memory_manager
