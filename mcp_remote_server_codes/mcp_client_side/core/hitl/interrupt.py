"""
Interrupt Handler for Human-in-the-Loop
=======================================
Manages interrupts for human approval during agent execution.

Features:
- Dynamic interrupts (within node execution)
- Interrupt state storage
- Resume with human response
- WebSocket notification integration
"""

from typing import Any, Dict, Optional, List, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import asyncio
import uuid

from motor.motor_asyncio import AsyncIOMotorClient


class InterruptType(str, Enum):
    """Types of interrupts."""
    APPROVAL_REQUIRED = "approval_required"
    INPUT_REQUIRED = "input_required"
    CONFIRMATION_REQUIRED = "confirmation_required"
    ERROR_RECOVERY = "error_recovery"
    CHECKPOINT = "checkpoint"


class InterruptStatus(str, Enum):
    """Status of an interrupt."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    EXPIRED = "expired"


@dataclass
class InterruptRequest:
    """An interrupt request waiting for human response."""
    id: str
    thread_id: str
    checkpoint_id: str
    interrupt_type: InterruptType
    message: str
    data: Dict[str, Any]
    status: InterruptStatus = InterruptStatus.PENDING
    response: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    responded_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class InterruptManager:
    """
    Manages interrupts for human-in-the-loop workflows.

    Stores pending interrupts in MongoDB and provides
    methods to create, respond to, and query interrupts.
    """

    def __init__(
        self,
        connection_string: str = "mongodb://localhost:27017",
        database_name: str = "agentic_bot",
        websocket_notify: Optional[Callable[[str, Dict], Awaitable[None]]] = None,
    ):
        self.client = AsyncIOMotorClient(connection_string)
        self.db = self.client[database_name]
        self.collection = self.db["interrupts"]
        self.websocket_notify = websocket_notify

        # In-memory waiting responses (for active sessions)
        self._pending_responses: Dict[str, asyncio.Event] = {}
        self._responses: Dict[str, Dict[str, Any]] = {}

    async def setup(self) -> None:
        """Create indexes for efficient queries."""
        await self.collection.create_index([
            ("thread_id", 1),
            ("status", 1)
        ])
        await self.collection.create_index([
            ("id", 1)
        ], unique=True)
        await self.collection.create_index(
            "expires_at",
            expireAfterSeconds=0
        )
        print("[InterruptManager] MongoDB indexes created")

    async def create_interrupt(
        self,
        thread_id: str,
        checkpoint_id: str,
        interrupt_type: InterruptType,
        message: str,
        data: Dict[str, Any],
        timeout_seconds: Optional[int] = 300,
    ) -> InterruptRequest:
        """
        Create a new interrupt request.

        Args:
            thread_id: The conversation thread ID
            checkpoint_id: Current checkpoint ID
            interrupt_type: Type of interrupt
            message: Human-readable message
            data: Additional data (tool call, action, etc.)
            timeout_seconds: Optional timeout for the interrupt

        Returns:
            InterruptRequest object
        """
        interrupt_id = f"int_{uuid.uuid4().hex[:12]}"

        request = InterruptRequest(
            id=interrupt_id,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            interrupt_type=interrupt_type,
            message=message,
            data=data,
        )

        # Fix: Use timedelta properly
        from datetime import timedelta
        request.expires_at = datetime.utcnow() + timedelta(seconds=timeout_seconds or 3600)

        # Store in MongoDB
        await self.collection.insert_one({
            "id": request.id,
            "thread_id": request.thread_id,
            "checkpoint_id": request.checkpoint_id,
            "interrupt_type": request.interrupt_type if isinstance(request.interrupt_type, str) else request.interrupt_type.value,
            "message": request.message,
            "data": request.data,
            "status": request.status if isinstance(request.status, str) else request.status.value,
            "response": request.response,
            "created_at": request.created_at,
            "responded_at": request.responded_at,
            "expires_at": request.expires_at,
        })

        # Create event for waiting
        self._pending_responses[interrupt_id] = asyncio.Event()

        # Notify via WebSocket if available
        if self.websocket_notify:
            await self.websocket_notify(thread_id, {
                "type": "interrupt",
                "interrupt_id": interrupt_id,
                "interrupt_type": interrupt_type if isinstance(interrupt_type, str) else interrupt_type.value,
                "message": message,
                "data": data,
            })

        print(f"[InterruptManager] Created interrupt: {interrupt_id}")
        return request

    async def wait_for_response(
        self,
        interrupt_id: str,
        timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Wait for human response to an interrupt.

        Args:
            interrupt_id: The interrupt ID
            timeout: Optional timeout in seconds

        Returns:
            Response data or None if timeout
        """
        event = self._pending_responses.get(interrupt_id)
        if not event:
            # Check if already responded in DB
            doc = await self.collection.find_one({"id": interrupt_id})
            if doc and doc["status"] != InterruptStatus.PENDING.value:
                return doc.get("response")
            return None

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self._responses.get(interrupt_id)
        except asyncio.TimeoutError:
            # Mark as expired
            await self.collection.update_one(
                {"id": interrupt_id},
                {"$set": {"status": InterruptStatus.EXPIRED.value}}
            )
            return None
        finally:
            # Cleanup
            self._pending_responses.pop(interrupt_id, None)
            self._responses.pop(interrupt_id, None)

    async def respond_to_interrupt(
        self,
        interrupt_id: str,
        status: InterruptStatus,
        response: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Respond to an interrupt.

        Args:
            interrupt_id: The interrupt ID
            status: Response status (approved, rejected, modified)
            response: Optional response data

        Returns:
            True if successful
        """
        result = await self.collection.update_one(
            {"id": interrupt_id, "status": InterruptStatus.PENDING.value},
            {
                "$set": {
                    "status": status if isinstance(status, str) else status.value,
                    "response": response,
                    "responded_at": datetime.utcnow(),
                }
            }
        )

        if result.modified_count == 0:
            return False

        # Store response for waiting coroutine
        self._responses[interrupt_id] = {
            "status": status if isinstance(status, str) else status.value,
            "response": response,
        }

        # Signal the waiting coroutine
        event = self._pending_responses.get(interrupt_id)
        if event:
            event.set()

        print(f"[InterruptManager] Responded to interrupt: {interrupt_id} -> {status if isinstance(status, str) else status.value}")
        return True

    async def get_pending_interrupts(
        self,
        thread_id: str
    ) -> List[InterruptRequest]:
        """Get all pending interrupts for a thread."""
        cursor = self.collection.find({
            "thread_id": thread_id,
            "status": InterruptStatus.PENDING.value
        }).sort("created_at", -1)

        interrupts = []
        async for doc in cursor:
            interrupts.append(InterruptRequest(
                id=doc["id"],
                thread_id=doc["thread_id"],
                checkpoint_id=doc["checkpoint_id"],
                interrupt_type=InterruptType(doc["interrupt_type"]),
                message=doc["message"],
                data=doc["data"],
                status=InterruptStatus(doc["status"]),
                response=doc.get("response"),
                created_at=doc["created_at"],
                responded_at=doc.get("responded_at"),
                expires_at=doc.get("expires_at"),
            ))

        return interrupts

    async def get_interrupt(self, interrupt_id: str) -> Optional[InterruptRequest]:
        """Get a specific interrupt by ID."""
        doc = await self.collection.find_one({"id": interrupt_id})
        if not doc:
            return None

        return InterruptRequest(
            id=doc["id"],
            thread_id=doc["thread_id"],
            checkpoint_id=doc["checkpoint_id"],
            interrupt_type=InterruptType(doc["interrupt_type"]),
            message=doc["message"],
            data=doc["data"],
            status=InterruptStatus(doc["status"]),
            response=doc.get("response"),
            created_at=doc["created_at"],
            responded_at=doc.get("responded_at"),
            expires_at=doc.get("expires_at"),
        )

    async def cancel_interrupt(self, interrupt_id: str) -> bool:
        """Cancel a pending interrupt."""
        result = await self.collection.delete_one({
            "id": interrupt_id,
            "status": InterruptStatus.PENDING.value
        })

        # Cleanup in-memory state
        event = self._pending_responses.pop(interrupt_id, None)
        if event:
            event.set()  # Release any waiting coroutine
        self._responses.pop(interrupt_id, None)

        return result.deleted_count > 0


# Singleton instance
_interrupt_manager: Optional[InterruptManager] = None


async def get_interrupt_manager(
    connection_string: str = "mongodb://localhost:27017",
    database_name: str = "First_mongoDB_database",
    websocket_notify: Optional[Callable] = None,
) -> InterruptManager:
    """Get or create the interrupt manager instance."""
    global _interrupt_manager

    if _interrupt_manager is None:
        _interrupt_manager = InterruptManager(
            connection_string=connection_string,
            database_name=database_name,
            websocket_notify=websocket_notify,
        )
        await _interrupt_manager.setup()
        print(f"[InterruptManager] Connected to MongoDB: {database_name}")

    return _interrupt_manager
