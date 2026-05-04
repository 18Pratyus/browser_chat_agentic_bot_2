"""
LangGraph State Definitions
===========================
Defines the state schema for the agentic bot graph.

State includes:
- Messages (conversation history)
- Tool calls and results
- Interrupt state
- Memory references
- Metadata
"""

from typing import Any, Dict, List, Optional, TypedDict, Annotated, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentStatus(str, Enum):
    """Status of the agent."""
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING_TOOL = "executing_tool"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    ERROR = "error"


class AgentState(TypedDict):
    """
    Main state for the agentic bot graph.

    This state is persisted via checkpointer and flows
    through all nodes in the graph.
    """
    # Core conversation
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Current status
    status: AgentStatus

    # Tool execution
    pending_tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    last_tool_call: Optional[Dict[str, Any]]

    # HITL - Interrupt state
    interrupt_id: Optional[str]
    interrupt_type: Optional[str]
    interrupt_data: Optional[Dict[str, Any]]
    awaiting_approval: bool

    # Memory references
    user_id: Optional[str]
    thread_id: str
    relevant_memories: List[Dict[str, Any]]
    facts_to_remember: List[str]
    
    # Smart caching (superhuman memory)
    feedback_cache: List[Dict[str, Any]]

    # Matched skill (Day 5)
    matched_skill: Optional[Dict[str, Any]]

    # Thinking/Reasoning (Day 5.5 - Chain of Thought)
    current_thinking: Optional[str]           # Raw thinking text
    thinking_steps: List[str]                 # Parsed thinking steps
    has_thinking: bool                        # Whether thinking was captured

    # Context selection: indices of user turns to include (None = all)
    selected_message_indices: Optional[List[int]]

    # Reflection
    should_reflect: bool
    reflection_result: Optional[Dict[str, Any]]
    error_count: int
    retry_count: int

    # Metadata
    created_at: str
    updated_at: str
    turn_count: int


def create_initial_state(
    thread_id: str,
    user_id: Optional[str] = None,
) -> AgentState:
    """Create an initial state for a new conversation."""
    now = datetime.utcnow().isoformat()

    return AgentState(
        messages=[],
        status=AgentStatus.IDLE,
        pending_tool_calls=[],
        tool_results=[],
        last_tool_call=None,
        interrupt_id=None,
        interrupt_type=None,
        interrupt_data=None,
        awaiting_approval=False,
        user_id=user_id,
        thread_id=thread_id,
        relevant_memories=[],
        facts_to_remember=[],
        feedback_cache=[],  # Smart cache for improvements
        matched_skill=None,  # Day 5: Matched skill from library
        current_thinking=None,  # Day 5.5: Chain of thought
        thinking_steps=[],
        has_thinking=False,
        selected_message_indices=None,
        should_reflect=False,
        reflection_result=None,
        error_count=0,
        retry_count=0,
        created_at=now,
        updated_at=now,
        turn_count=0,
    )


class ToolCallState(TypedDict):
    """State for a single tool call."""
    id: str
    name: str
    args: Dict[str, Any]
    status: str  # "pending", "approved", "rejected", "completed", "failed"
    result: Optional[Any]
    error: Optional[str]
    requires_approval: bool
    risk_level: str


class ReflectionState(TypedDict):
    """State for reflection operations."""
    action_taken: str
    action_result: Any
    success: bool
    user_feedback: Optional[str]
    lesson_learned: Optional[str]
    improved_approach: Optional[str]


class MemoryContext(TypedDict):
    """Context from memory for the current turn."""
    user_preferences: Dict[str, Any]
    relevant_facts: List[str]
    recent_skills_used: List[str]
    error_lessons: List[Dict[str, Any]]
