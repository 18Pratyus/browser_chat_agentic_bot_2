"""
Time Travel API Endpoints
=========================
REST API for conversation history and time travel features.

Endpoints:
- GET /api/history/{thread_id} - Get conversation timeline
- GET /api/history/{thread_id}/{checkpoint_id} - Get state at checkpoint
- POST /api/history/rewind - Rewind to a checkpoint
- POST /api/history/branch - Create a branch from checkpoint
- DELETE /api/history/{thread_id} - Delete a conversation
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.hitl import get_time_travel_manager, StateSnapshot, TimeTravelResult

router = APIRouter(prefix="/api/history", tags=["history"])


class RewindRequest(BaseModel):
    """Request to rewind to a checkpoint."""
    thread_id: str
    checkpoint_id: str


class BranchRequest(BaseModel):
    """Request to create a branch."""
    source_thread_id: str
    checkpoint_id: str
    new_thread_id: Optional[str] = None


class TimelineResponse(BaseModel):
    """Response for timeline request."""
    thread_id: str
    checkpoints: list
    total: int


class StateResponse(BaseModel):
    """Response for state request."""
    checkpoint_id: str
    thread_id: str
    created_at: str
    messages: list
    metadata: dict
    # Day 5.5: Thinking/Reasoning persistence
    thinking: Optional[str] = None
    thinking_steps: Optional[list] = None


class RewindResponse(BaseModel):
    """Response for rewind request."""
    success: bool
    message: str
    checkpoint_id: Optional[str] = None
    config: Optional[dict] = None


class BranchResponse(BaseModel):
    """Response for branch request."""
    success: bool
    message: str
    new_thread_id: Optional[str] = None
    source_checkpoint_id: Optional[str] = None


def get_message_preview(messages: list, max_length: int = 50) -> dict:
    """Extract last user and AI message for preview."""
    last_user = None
    last_ai = None

    for msg in reversed(messages):
        # Handle both LangChain message objects and dicts
        if hasattr(msg, "__class__"):
            msg_type = msg.__class__.__name__
        else:
            msg_type = ""

        # Get content - handle objects and dicts
        if hasattr(msg, "content"):
            content = msg.content
        elif isinstance(msg, dict):
            content = msg.get("content", msg.get("data", {}).get("content", ""))
            msg_type = msg.get("type", msg.get("data", {}).get("type", ""))
        else:
            content = str(msg)

        # Normalize type names
        if "human" in str(msg_type).lower() or msg_type == "human":
            if not last_user and content:
                last_user = content[:max_length] + ("..." if len(content) > max_length else "")
        elif "ai" in str(msg_type).lower() or msg_type == "ai":
            if not last_ai and content:
                last_ai = content[:max_length] + ("..." if len(content) > max_length else "")

        if last_user and last_ai:
            break

    return {
        "last_user_message": last_user,
        "last_ai_message": last_ai,
    }


@router.get("/{thread_id}")
async def get_timeline(
    thread_id: str,
    limit: int = 50
) -> TimelineResponse:
    """
    Get the conversation timeline.

    Returns a list of checkpoints for the thread,
    ordered by creation time (newest first).
    """
    time_travel = await get_time_travel_manager()
    snapshots = await time_travel.get_timeline(thread_id, limit=limit)

    return TimelineResponse(
        thread_id=thread_id,
        checkpoints=[
            {
                "checkpoint_id": s.checkpoint_id,
                "created_at": s.created_at.isoformat(),
                "message_count": len(s.messages),
                "metadata": s.metadata,
                "parent_checkpoint_id": s.parent_checkpoint_id,
                "preview": get_message_preview(s.messages),
            }
            for s in snapshots
        ],
        total=len(snapshots),
    )


def extract_tool_calls(msg) -> list:
    """Extract tool calls from an AIMessage object."""
    tool_calls = []

    # Check for tool_calls attribute (LangChain AIMessage)
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            if isinstance(tc, dict):
                tool_calls.append({
                    "name": tc.get("name", "unknown"),
                    "args": tc.get("args", {}),
                    "id": tc.get("id", ""),
                })
            else:
                # Handle ToolCall object
                tool_calls.append({
                    "name": getattr(tc, "name", "unknown"),
                    "args": getattr(tc, "args", {}),
                    "id": getattr(tc, "id", ""),
                })

    # Also check additional_kwargs for tool_calls (OpenAI format)
    if hasattr(msg, "additional_kwargs"):
        additional = msg.additional_kwargs
        if isinstance(additional, dict) and "tool_calls" in additional:
            for tc in additional["tool_calls"]:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    tool_calls.append({
                        "name": func.get("name", "unknown"),
                        "args": func.get("arguments", {}),
                        "id": tc.get("id", ""),
                    })

    return tool_calls


@router.get("/{thread_id}/{checkpoint_id}")
async def get_state_at_checkpoint(
    thread_id: str,
    checkpoint_id: str
) -> StateResponse:
    """
    Get the full state at a specific checkpoint.

    Includes messages, metadata, and tool_calls for AIMessage objects.
    """
    time_travel = await get_time_travel_manager()
    snapshot = await time_travel.get_state_at(thread_id, checkpoint_id)

    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"Checkpoint {checkpoint_id} not found in thread {thread_id}"
        )

    # Build messages with tool_calls for AI messages
    messages_with_tools = []
    for msg in snapshot.messages:
        msg_data = {
            "type": msg.__class__.__name__,
            "content": msg.content if hasattr(msg, "content") else str(msg),
        }

        # Extract tool_calls for AIMessage
        if "AI" in msg.__class__.__name__ or msg.__class__.__name__ == "AIMessage":
            tool_calls = extract_tool_calls(msg)
            if tool_calls:
                msg_data["tool_calls"] = tool_calls

        messages_with_tools.append(msg_data)

    # Extract thinking from metadata (Day 5.5)
    thinking = snapshot.metadata.get("current_thinking") if snapshot.metadata else None
    thinking_steps = snapshot.metadata.get("thinking_steps") if snapshot.metadata else None

    return StateResponse(
        checkpoint_id=snapshot.checkpoint_id,
        thread_id=snapshot.thread_id,
        created_at=snapshot.created_at.isoformat(),
        messages=messages_with_tools,
        metadata=snapshot.metadata,
        thinking=thinking,
        thinking_steps=thinking_steps,
    )


@router.post("/rewind")
async def rewind_to_checkpoint(request: RewindRequest) -> RewindResponse:
    """
    Prepare to rewind to a specific checkpoint.

    Returns the config needed to resume from that checkpoint.
    The actual rewind happens when the graph is invoked with this config.
    """
    time_travel = await get_time_travel_manager()
    result = await time_travel.rewind_to(request.thread_id, request.checkpoint_id)

    return RewindResponse(
        success=result.success,
        message=result.message,
        checkpoint_id=result.checkpoint_id,
        config=result.state,
    )


@router.post("/branch")
async def create_branch(request: BranchRequest) -> BranchResponse:
    """
    Create a new branch from a specific checkpoint.

    This allows exploring alternative paths from a past state.
    """
    time_travel = await get_time_travel_manager()
    result = await time_travel.branch_from(
        request.source_thread_id,
        request.checkpoint_id,
        request.new_thread_id,
    )

    return BranchResponse(
        success=result.success,
        message=result.message,
        new_thread_id=result.new_thread_id,
        source_checkpoint_id=result.checkpoint_id,
    )


@router.get("/{thread_id}/compare/{checkpoint_id_1}/{checkpoint_id_2}")
async def compare_checkpoints(
    thread_id: str,
    checkpoint_id_1: str,
    checkpoint_id_2: str
):
    """
    Compare two checkpoints and return the differences.

    Useful for understanding what changed between two points in time.
    """
    time_travel = await get_time_travel_manager()
    comparison = await time_travel.compare_states(
        thread_id,
        checkpoint_id_1,
        checkpoint_id_2,
    )

    return comparison


@router.delete("/{thread_id}")
async def delete_thread(thread_id: str):
    """
    Delete a conversation thread and all its checkpoints.

    This is irreversible!
    """
    time_travel = await get_time_travel_manager()
    success = await time_travel.delete_branch(thread_id)

    if success:
        return {"success": True, "message": f"Thread {thread_id} deleted"}
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Thread {thread_id} not found or already deleted"
        )
