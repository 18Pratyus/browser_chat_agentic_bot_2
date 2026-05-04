"""
MongoDB Checkpointer for LangGraph
==================================
Short-term memory: Saves conversation state at every graph step.
Enables: Resume conversations, Time travel, State rewind.

Uses MongoDB as persistent storage backend.
"""

from typing import Any, AsyncIterator, Optional, Sequence, Tuple
from datetime import datetime
import json

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
)
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


class MongoDBCheckpointer(BaseCheckpointSaver):
    """
    MongoDB-based checkpointer for LangGraph.

    Stores conversation state in MongoDB for:
    - Conversation persistence across page refreshes
    - Time travel (rewind to any past state)
    - Branching (fork execution from past state)

    Collections:
    - checkpoints: Stores checkpoint data
    - checkpoint_writes: Stores pending writes
    """

    def __init__(
        self,
        connection_string: str = "mongodb://localhost:27017",
        database_name: str = "agentic_bot",
        collection_name: str = "checkpoints",
        serde: Optional[SerializerProtocol] = None,
    ):
        super().__init__(serde=serde)
        self.client = AsyncIOMotorClient(connection_string)
        self.db: AsyncIOMotorDatabase = self.client[database_name]
        self.collection = self.db[collection_name]
        self.writes_collection = self.db[f"{collection_name}_writes"]

    async def setup(self) -> None:
        """Create indexes for efficient queries."""
        # Index for thread_id + checkpoint_ns + checkpoint_id
        await self.collection.create_index([
            ("thread_id", 1),
            ("checkpoint_ns", 1),
            ("checkpoint_id", -1)
        ])

        # Index for time-based queries
        await self.collection.create_index([
            ("thread_id", 1),
            ("created_at", -1)
        ])

        # Index for writes collection
        await self.writes_collection.create_index([
            ("thread_id", 1),
            ("checkpoint_ns", 1),
            ("checkpoint_id", 1)
        ])

        print(f"[Checkpointer] MongoDB indexes created on {self.collection.name}")

    async def aget_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        """Get a checkpoint tuple by config."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        query = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
        }

        if checkpoint_id:
            query["checkpoint_id"] = checkpoint_id

        # Get the most recent checkpoint matching the query
        doc = await self.collection.find_one(
            query,
            sort=[("checkpoint_id", -1)]
        )

        if not doc:
            return None

        # Get pending writes for this checkpoint
        writes_cursor = self.writes_collection.find({
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": doc["checkpoint_id"]
        })

        pending_writes = []
        async for write_doc in writes_cursor:
            pending_writes.append((
                write_doc["task_id"],
                write_doc["channel"],
                self.serde.loads(write_doc["value"])
            ))

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": doc["checkpoint_id"],
                }
            },
            checkpoint=self.serde.loads(doc["checkpoint"]),
            metadata=self.serde.loads(doc["metadata"]) if doc.get("metadata") else {},
            parent_config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": doc["parent_checkpoint_id"],
                }
            } if doc.get("parent_checkpoint_id") else None,
            pending_writes=pending_writes,
        )

    async def alist(
        self,
        config: Optional[dict] = None,
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """List checkpoints, optionally filtered."""
        query = {}

        if config:
            thread_id = config["configurable"]["thread_id"]
            checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
            query["thread_id"] = thread_id
            query["checkpoint_ns"] = checkpoint_ns

        if before:
            before_id = before["configurable"].get("checkpoint_id")
            if before_id:
                query["checkpoint_id"] = {"$lt": before_id}

        cursor = self.collection.find(query).sort("checkpoint_id", -1)

        if limit:
            cursor = cursor.limit(limit)

        async for doc in cursor:
            yield CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": doc["thread_id"],
                        "checkpoint_ns": doc["checkpoint_ns"],
                        "checkpoint_id": doc["checkpoint_id"],
                    }
                },
                checkpoint=self.serde.loads(doc["checkpoint"]),
                metadata=self.serde.loads(doc["metadata"]) if doc.get("metadata") else {},
                parent_config={
                    "configurable": {
                        "thread_id": doc["thread_id"],
                        "checkpoint_ns": doc["checkpoint_ns"],
                        "checkpoint_id": doc["parent_checkpoint_id"],
                    }
                } if doc.get("parent_checkpoint_id") else None,
            )

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict,
    ) -> dict:
        """Save a checkpoint."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        # Generate new checkpoint ID
        checkpoint_id = checkpoint["id"]

        doc = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_checkpoint_id,
            "checkpoint": self.serde.dumps(checkpoint),
            "metadata": self.serde.dumps(metadata),
            "created_at": datetime.utcnow(),
        }

        await self.collection.insert_one(doc)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: dict,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Save pending writes for a checkpoint."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        docs = [
            {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "channel": channel,
                "value": self.serde.dumps(value),
                "created_at": datetime.utcnow(),
            }
            for channel, value in writes
        ]

        if docs:
            await self.writes_collection.insert_many(docs)

    async def adelete_thread(self, thread_id: str) -> None:
        """Delete all checkpoints for a thread."""
        await self.collection.delete_many({"thread_id": thread_id})
        await self.writes_collection.delete_many({"thread_id": thread_id})
        print(f"[Checkpointer] Deleted thread: {thread_id}")

    async def get_thread_history(
        self,
        thread_id: str,
        limit: int = 50
    ) -> list:
        """Get checkpoint history for a thread (for UI timeline)."""
        cursor = self.collection.find(
            {"thread_id": thread_id},
            {"checkpoint_id": 1, "created_at": 1, "metadata": 1}
        ).sort("created_at", -1).limit(limit)

        history = []
        async for doc in cursor:
            metadata = self.serde.loads(doc["metadata"]) if doc.get("metadata") else {}
            history.append({
                "checkpoint_id": doc["checkpoint_id"],
                "created_at": doc["created_at"].isoformat(),
                "step": metadata.get("step"),
                "source": metadata.get("source"),
            })

        return history


# Singleton instance
_checkpointer: Optional[MongoDBCheckpointer] = None


async def get_checkpointer(
    connection_string: str = "mongodb://localhost:27017",
    database_name: str = "First_mongoDB_database"
) -> MongoDBCheckpointer:
    """Get or create the MongoDB checkpointer instance."""
    global _checkpointer

    if _checkpointer is None:
        _checkpointer = MongoDBCheckpointer(
            connection_string=connection_string,
            database_name=database_name,
            collection_name="checkpoints"
        )
        await _checkpointer.setup()
        print(f"[Checkpointer] Connected to MongoDB: {database_name}")

    return _checkpointer
