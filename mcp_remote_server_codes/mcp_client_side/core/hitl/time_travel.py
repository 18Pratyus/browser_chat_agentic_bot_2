"""
Time Travel System
==================
Navigate through conversation history, rewind to past states, and branch.

Features:
- Get state at any checkpoint
- Rewind to any past state
- Branch execution from past state
- Compare states (diff)
"""

from typing import Any, Dict, Optional, List
from datetime import datetime
from dataclasses import dataclass

from core.memory import MongoDBCheckpointer, get_checkpointer


@dataclass
class StateSnapshot:
    """A snapshot of conversation state."""
    checkpoint_id: str
    thread_id: str
    created_at: datetime
    messages: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    parent_checkpoint_id: Optional[str] = None


@dataclass
class TimeTravelResult:
    """Result of a time travel operation."""
    success: bool
    message: str
    new_thread_id: Optional[str] = None
    checkpoint_id: Optional[str] = None
    state: Optional[Dict[str, Any]] = None


class TimeTravelManager:
    """
    Manages time travel operations for conversations.

    Enables:
    - Viewing conversation history as timeline
    - Rewinding to any past checkpoint
    - Branching from a past state
    - Comparing states at different checkpoints
    """

    def __init__(self, checkpointer: MongoDBCheckpointer):
        self.checkpointer = checkpointer

    async def get_timeline(
        self,
        thread_id: str,
        limit: int = 50
    ) -> List[StateSnapshot]:
        """
        Get the conversation timeline (list of checkpoints).

        Args:
            thread_id: The conversation thread ID
            limit: Maximum number of checkpoints to return

        Returns:
            List of StateSnapshot objects ordered by time
        """
        config = {"configurable": {"thread_id": thread_id}}

        snapshots = []
        async for checkpoint_tuple in self.checkpointer.alist(config, limit=limit):
            checkpoint = checkpoint_tuple.checkpoint
            metadata = checkpoint_tuple.metadata or {}

            # Extract messages from checkpoint
            messages = []
            if "channel_values" in checkpoint:
                messages = checkpoint["channel_values"].get("messages", [])

            parent_id = None
            if checkpoint_tuple.parent_config:
                parent_id = checkpoint_tuple.parent_config["configurable"].get("checkpoint_id")

            snapshots.append(StateSnapshot(
                checkpoint_id=checkpoint_tuple.config["configurable"]["checkpoint_id"],
                thread_id=thread_id,
                created_at=datetime.fromisoformat(
                    checkpoint.get("ts", datetime.utcnow().isoformat())
                ) if "ts" in checkpoint else datetime.utcnow(),
                messages=messages,
                metadata=metadata,
                parent_checkpoint_id=parent_id,
            ))

        return snapshots

    async def get_state_at(
        self,
        thread_id: str,
        checkpoint_id: str
    ) -> Optional[StateSnapshot]:
        """
        Get the state at a specific checkpoint.

        Args:
            thread_id: The conversation thread ID
            checkpoint_id: The checkpoint ID to retrieve

        Returns:
            StateSnapshot or None if not found
        """
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id
            }
        }

        checkpoint_tuple = await self.checkpointer.aget_tuple(config)
        if not checkpoint_tuple:
            return None

        checkpoint = checkpoint_tuple.checkpoint
        metadata = checkpoint_tuple.metadata or {}

        messages = []
        channel_values = checkpoint.get("channel_values", {})
        if channel_values:
            messages = channel_values.get("messages", [])

        # Day 5.5: Extract thinking from channel_values (state)
        thinking_metadata = {
            "current_thinking": channel_values.get("current_thinking"),
            "thinking_steps": channel_values.get("thinking_steps", []),
            "has_thinking": channel_values.get("has_thinking", False),
        }
        # Merge with existing metadata
        full_metadata = {**metadata, **thinking_metadata}

        parent_id = None
        if checkpoint_tuple.parent_config:
            parent_id = checkpoint_tuple.parent_config["configurable"].get("checkpoint_id")

        return StateSnapshot(
            checkpoint_id=checkpoint_id,
            thread_id=thread_id,
            created_at=datetime.fromisoformat(
                checkpoint.get("ts", datetime.utcnow().isoformat())
            ) if "ts" in checkpoint else datetime.utcnow(),
            messages=messages,
            metadata=full_metadata,
            parent_checkpoint_id=parent_id,
        )

    async def rewind_to(
        self,
        thread_id: str,
        checkpoint_id: str
    ) -> TimeTravelResult:
        """
        Prepare to rewind to a specific checkpoint.

        Note: This returns the config needed to resume from
        that checkpoint. The actual rewind happens when the
        graph is invoked with this config.

        Args:
            thread_id: The conversation thread ID
            checkpoint_id: The checkpoint to rewind to

        Returns:
            TimeTravelResult with config for graph invocation
        """
        # Verify the checkpoint exists
        snapshot = await self.get_state_at(thread_id, checkpoint_id)
        if not snapshot:
            return TimeTravelResult(
                success=False,
                message=f"Checkpoint {checkpoint_id} not found"
            )

        return TimeTravelResult(
            success=True,
            message=f"Ready to rewind to checkpoint {checkpoint_id}",
            checkpoint_id=checkpoint_id,
            state={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id
                }
            }
        )

    async def branch_from(
        self,
        source_thread_id: str,
        checkpoint_id: str,
        new_thread_id: Optional[str] = None
    ) -> TimeTravelResult:
        """
        Create a new branch from a specific checkpoint.

        This creates a new thread that starts from the state
        at the specified checkpoint, allowing parallel exploration.

        Args:
            source_thread_id: Original thread ID
            checkpoint_id: Checkpoint to branch from
            new_thread_id: Optional new thread ID (auto-generated if not provided)

        Returns:
            TimeTravelResult with new thread info
        """
        import uuid

        # Verify source checkpoint exists
        snapshot = await self.get_state_at(source_thread_id, checkpoint_id)
        if not snapshot:
            return TimeTravelResult(
                success=False,
                message=f"Checkpoint {checkpoint_id} not found in thread {source_thread_id}"
            )

        # Generate new thread ID if not provided
        if not new_thread_id:
            new_thread_id = f"branch_{source_thread_id}_{uuid.uuid4().hex[:8]}"

        return TimeTravelResult(
            success=True,
            message=f"Branch created: {new_thread_id}",
            new_thread_id=new_thread_id,
            checkpoint_id=checkpoint_id,
            state={
                "source_thread": source_thread_id,
                "source_checkpoint": checkpoint_id,
                "messages": snapshot.messages,
            }
        )

    async def compare_states(
        self,
        thread_id: str,
        checkpoint_id_1: str,
        checkpoint_id_2: str
    ) -> Dict[str, Any]:
        """
        Compare two checkpoints and return the differences.

        Args:
            thread_id: The conversation thread ID
            checkpoint_id_1: First checkpoint
            checkpoint_id_2: Second checkpoint

        Returns:
            Dictionary with differences between the two states
        """
        state1 = await self.get_state_at(thread_id, checkpoint_id_1)
        state2 = await self.get_state_at(thread_id, checkpoint_id_2)

        if not state1 or not state2:
            return {
                "error": "One or both checkpoints not found",
                "checkpoint_1_found": state1 is not None,
                "checkpoint_2_found": state2 is not None,
            }

        # Compare messages
        messages_diff = {
            "checkpoint_1_message_count": len(state1.messages),
            "checkpoint_2_message_count": len(state2.messages),
            "new_messages": state2.messages[len(state1.messages):] if len(state2.messages) > len(state1.messages) else [],
        }

        return {
            "checkpoint_1": {
                "id": checkpoint_id_1,
                "created_at": state1.created_at.isoformat(),
                "message_count": len(state1.messages),
            },
            "checkpoint_2": {
                "id": checkpoint_id_2,
                "created_at": state2.created_at.isoformat(),
                "message_count": len(state2.messages),
            },
            "messages_diff": messages_diff,
            "time_diff_seconds": (state2.created_at - state1.created_at).total_seconds(),
        }

    async def delete_branch(self, thread_id: str) -> bool:
        """
        Delete a branch (all checkpoints for a thread).

        Args:
            thread_id: The thread ID to delete

        Returns:
            True if successful
        """
        await self.checkpointer.adelete_thread(thread_id)
        return True


# Singleton
_time_travel: Optional[TimeTravelManager] = None


async def get_time_travel_manager(
    connection_string: str = "mongodb://localhost:27017",
    database_name: str = "First_mongoDB_database"
) -> TimeTravelManager:
    """Get or create the time travel manager instance."""
    global _time_travel

    if _time_travel is None:
        checkpointer = await get_checkpointer(connection_string, database_name)
        _time_travel = TimeTravelManager(checkpointer)
        print("[TimeTravelManager] Initialized")

    return _time_travel
