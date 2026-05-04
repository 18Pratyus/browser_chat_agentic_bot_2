"""
Main Agent Graph with HITL Support
==================================
The core LangGraph workflow with:
- Memory integration
- Human-in-the-loop approvals
- Time travel support
- Reflection and learning
"""

from typing import Any, Dict, List, Optional
from functools import partial

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from .state import AgentState, AgentStatus, create_initial_state
from .nodes import (
    agent_node,
    tool_execution_node,
    memory_retrieval_node,
    memory_storage_node,
    reflection_node,
    interrupt_resume_node,
    should_continue,
    # Day 4: Feedback processing
    feedback_processing_node,
    check_for_improvements_node,
    detect_negative_feedback,
    # Day 5: Skill retrieval
    skill_retrieval_node,
)


class AgenticGraphBuilder:
    """
    Builder for the main agent graph.

    Constructs a LangGraph with all AGI features:
    - Memory retrieval and storage
    - Tool execution with approval gates
    - HITL interrupts and time travel
    - Reflection and self-improvement (Day 4)
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: List[BaseTool],
        checkpointer: Optional[BaseCheckpointSaver] = None,
        memory_manager: Optional[Any] = None,
        interrupt_manager: Optional[Any] = None,
        approval_gates: Optional[Any] = None,
        reflection_system: Optional[Any] = None,  # Day 4
        improvement_store: Optional[Any] = None,  # Day 4
        skill_store: Optional[Any] = None,  # Day 5
    ):
        self.llm = llm
        self.tools = tools
        self.checkpointer = checkpointer
        self.memory_manager = memory_manager
        self.interrupt_manager = interrupt_manager
        self.approval_gates = approval_gates
        self.reflection_system = reflection_system  # Day 4
        self.improvement_store = improvement_store  # Day 4
        self.skill_store = skill_store  # Day 5

        # Bind tools to LLM
        self.llm_with_tools = llm.bind_tools(tools) if tools else llm

    def build(self) -> StateGraph:
        """Build and return the compiled graph."""
        # Create the graph
        graph = StateGraph(AgentState)

        # ══════════════════════════════════════════════════════════════
        # ADD NODES
        # ══════════════════════════════════════════════════════════════

        # Memory retrieval node
        graph.add_node(
            "memory",
            partial(self._memory_node)
        )

        # Main agent node
        graph.add_node(
            "agent",
            partial(self._agent_node)
        )

        # Tool execution node
        graph.add_node(
            "tools",
            partial(self._tools_node)
        )

        # Reflection node
        graph.add_node(
            "reflect",
            partial(self._reflect_node)
        )

        # Interrupt handling node
        graph.add_node(
            "interrupt",
            partial(self._interrupt_node)
        )

        # Memory storage node
        graph.add_node(
            "store_memory",
            partial(self._store_memory_node)
        )

        # Feedback processing node (Day 4 - Prompt Improvements)
        graph.add_node(
            "process_feedback",
            partial(self._feedback_node)
        )

        # Check for improvements node (retrieves past learnings)
        graph.add_node(
            "check_improvements",
            partial(self._check_improvements_node)
        )

        # Skill retrieval node (Day 5 - matches learned skills)
        graph.add_node(
            "check_skills",
            partial(self._skill_retrieval_node)
        )

        # ══════════════════════════════════════════════════════════════
        # ADD EDGES
        # ══════════════════════════════════════════════════════════════

        # Start -> Memory retrieval
        graph.add_edge(START, "memory")

        # Memory -> Check for feedback or normal flow
        graph.add_conditional_edges(
            "memory",
            self._route_after_memory,
            {
                "process_feedback": "process_feedback",
                "check_improvements": "check_improvements",  # Normal flow now goes here
            }
        )

        # Check improvements -> Check skills (Day 5)
        graph.add_edge("check_improvements", "check_skills")

        # Check skills -> Agent (with matched skills context)
        graph.add_edge("check_skills", "agent")

        # Feedback processing -> Agent (with improved context)
        graph.add_edge("process_feedback", "agent")

        # Agent -> Conditional routing
        graph.add_conditional_edges(
            "agent",
            self._route_after_agent,
            {
                "tools": "tools",
                "reflect": "reflect",
                "end": "store_memory",
            }
        )

        # Tools -> Conditional routing
        graph.add_conditional_edges(
            "tools",
            self._route_after_tools,
            {
                "agent": "agent",
                "interrupt": "interrupt",
                "reflect": "reflect",
            }
        )

        # Reflection -> Agent (for retry) or Store memory
        graph.add_conditional_edges(
            "reflect",
            self._route_after_reflect,
            {
                "agent": "agent",
                "end": "store_memory",
            }
        )

        # Interrupt -> Resume when human responds
        graph.add_edge("interrupt", "tools")

        # Store memory -> END
        graph.add_edge("store_memory", END)

        # ══════════════════════════════════════════════════════════════
        # COMPILE
        # ══════════════════════════════════════════════════════════════

        compiled = graph.compile(
            checkpointer=self.checkpointer,
            interrupt_before=["tools"] if self.approval_gates else None,
        )

        return compiled

    # ══════════════════════════════════════════════════════════════════
    # NODE IMPLEMENTATIONS
    # ══════════════════════════════════════════════════════════════════

    async def _memory_node(self, state: AgentState) -> Dict[str, Any]:
        """Retrieve relevant memories and lessons (Day 4)."""
        return await memory_retrieval_node(
            state,
            self.memory_manager,
            self.improvement_store,  # Day 4: Smart lesson retrieval
        )

    async def _agent_node(self, state: AgentState) -> Dict[str, Any]:
        """Main agent reasoning."""
        return await agent_node(state, self.llm_with_tools)

    async def _tools_node(self, state: AgentState) -> Dict[str, Any]:
        """Execute tools with approval gates."""
        if not self.approval_gates or not self.interrupt_manager:
            # Simple tool execution without gates
            from langgraph.prebuilt import ToolNode
            tool_node = ToolNode(self.tools)
            return await tool_node.ainvoke(state)

        return await tool_execution_node(
            state,
            self.tools,
            self.approval_gates,
            self.interrupt_manager,
        )

    async def _reflect_node(self, state: AgentState) -> Dict[str, Any]:
        """Self-reflection and learning (Day 4)."""
        return await reflection_node(
            state,
            self.llm,
            self.memory_manager,
            self.reflection_system,  # Day 4 intelligence module
        )

    async def _interrupt_node(self, state: AgentState) -> Dict[str, Any]:
        """Handle interrupt resume."""
        if not self.interrupt_manager:
            return {"awaiting_approval": False}

        return await interrupt_resume_node(
            state,
            self.interrupt_manager,
            self.tools,
        )

    async def _store_memory_node(self, state: AgentState) -> Dict[str, Any]:
        """Store learned facts."""
        if not self.memory_manager:
            return {}

        return await memory_storage_node(state, self.memory_manager)

    async def _feedback_node(self, state: AgentState) -> Dict[str, Any]:
        """Process negative feedback and learn from it (Day 4)."""
        if not self.improvement_store:
            return {}

        return await feedback_processing_node(
            state,
            self.llm,
            self.improvement_store,
        )

    async def _check_improvements_node(self, state: AgentState) -> Dict[str, Any]:
        """Check for relevant improvements from past feedback (superhuman memory)."""
        if not self.improvement_store:
            return {}

        return await check_for_improvements_node(state, self.improvement_store)

    async def _skill_retrieval_node(self, state: AgentState) -> Dict[str, Any]:
        """Check for matching learned skills (Day 5)."""
        if not self.skill_store:
            return {}

        return await skill_retrieval_node(state, self.skill_store)


    # ══════════════════════════════════════════════════════════════════
    # ROUTING FUNCTIONS
    # ══════════════════════════════════════════════════════════════════

    def _route_after_memory(self, state: AgentState) -> str:
        """Route after memory node - check if this is negative feedback."""
        from langchain_core.messages import HumanMessage

        # Get the last user message
        messages = state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_msg = msg.content
                # Check if it's negative feedback
                is_negative, _ = detect_negative_feedback(user_msg)
                if is_negative and len(messages) >= 3:
                    # Only process feedback if we have enough context
                    # (original prompt + LLM response + feedback)
                    print(f"[ROUTE] Detected negative feedback, routing to process_feedback")
                    return "process_feedback"
                break

        return "check_improvements"  # Go through improvements check first

    def _route_after_agent(self, state: AgentState) -> str:
        """Route after agent node."""
        # Check for tool calls
        messages = state.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"

        # Check if reflection needed
        if state.get("should_reflect"):
            return "reflect"

        return "end"

    def _route_after_tools(self, state: AgentState) -> str:
        """Route after tools node."""
        # Check if waiting for approval
        if state.get("awaiting_approval"):
            return "interrupt"

        # Check if reflection needed (after errors)
        if state.get("error_count", 0) > 0:
            return "reflect"

        return "agent"

    def _route_after_reflect(self, state: AgentState) -> str:
        """Route after reflection node."""
        # If reflection suggests retry
        reflection = state.get("reflection_result", {})
        if reflection.get("should_retry"):
            return "agent"

        return "end"


async def create_agentic_graph(
    llm: BaseChatModel,
    tools: List[BaseTool],
    connection_string: str = "mongodb://localhost:27017",
    database_name: str = "First_mongoDB_database",
    enable_memory: bool = True,
    enable_hitl: bool = True,
    enable_reflection: bool = True,
) -> StateGraph:
    """
    Create a fully-featured agentic graph.

    Args:
        llm: The language model
        tools: List of tools available to the agent
        connection_string: MongoDB connection string
        database_name: MongoDB database name
        enable_memory: Enable memory features
        enable_hitl: Enable human-in-the-loop
        enable_reflection: Enable reflection/learning (Day 4)

    Returns:
        Compiled LangGraph
    """
    # Import modules
    from core.memory import get_checkpointer, get_memory_manager
    from core.hitl import get_interrupt_manager, get_approval_gates

    # Initialize components
    checkpointer = None
    memory_manager = None
    interrupt_manager = None
    approval_gates = None
    reflection_system = None
    improvement_store = None

    if enable_memory:
        checkpointer = await get_checkpointer(connection_string, database_name)
        memory_manager = await get_memory_manager(connection_string, database_name)

    if enable_hitl:
        interrupt_manager = await get_interrupt_manager(connection_string, database_name)
        approval_gates = get_approval_gates()

    # Day 4: Initialize intelligence/reflection components
    skill_store = None
    if enable_reflection:
        try:
            from core.intelligence import get_improvement_store, get_reflection_system, get_skill_store

            improvement_store = await get_improvement_store(connection_string, database_name)
            reflection_system = await get_reflection_system(llm, improvement_store)
            print("  ✓ Intelligence module initialized (Day 4)")

            # Day 5: Initialize skill store
            skill_store = await get_skill_store(connection_string, database_name)
            print("  ✓ Skill Store initialized (Day 5)")

        except Exception as e:
            print(f"  ⚠ Intelligence module failed: {e}")
            reflection_system = None
            improvement_store = None
            skill_store = None

    # Build the graph
    builder = AgenticGraphBuilder(
        llm=llm,
        tools=tools,
        checkpointer=checkpointer,
        memory_manager=memory_manager,
        interrupt_manager=interrupt_manager,
        approval_gates=approval_gates if enable_hitl else None,
        reflection_system=reflection_system,
        improvement_store=improvement_store,
        skill_store=skill_store,  # Day 5
    )

    return builder.build()
