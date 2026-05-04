"""
LangGraph Nodes
===============
Defines individual nodes for the agent graph.

Nodes:
- agent_node: Main LLM reasoning
- tool_node: Tool execution with approval gates
- memory_node: Memory retrieval and storage
- reflection_node: Self-critique and learning
- interrupt_node: Handle human interrupts
"""

from typing import Any, Dict, Literal, Optional, List, Callable
from datetime import datetime
from contextvars import ContextVar

# Set this per-request in app.py before astream; tool_execution_node reads it to emit screenshots
ws_emit_var: ContextVar[Optional[Callable]] = ContextVar("ws_emit_var", default=None)

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from .state import AgentState, AgentStatus, ToolCallState

# Import reasoning module for chain-of-thought
try:
    from core.intelligence.reasoning import (
        parse_thinking_response,
        get_reasoning_system_message,
        REASONING_SYSTEM_PROMPT,
    )
    REASONING_AVAILABLE = True
except ImportError:
    REASONING_AVAILABLE = False
    print("[NODES] Warning: reasoning module not available")


# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS FOR STRUCTURED LLM PARSING
# ═══════════════════════════════════════════════════════════════════════════════

class ReasoningResponse(BaseModel):
    """Structured output for chain-of-thought reasoning (Day 5.5).

    Forces LLM to provide step-by-step thinking with guaranteed structure.
    """
    thinking: str = Field(
        description="Your detailed step-by-step reasoning process. Explain HOW you're analyzing the request, WHAT you're considering, and WHY you're choosing your approach."
    )
    thinking_steps: List[str] = Field(
        description="List of individual reasoning steps. Each step should be a clear, actionable thought (e.g., '1. User is asking about expenses', '2. I need to check the database')"
    )
    answer: str = Field(
        description="Your final response to the user. This is what they will see."
    )


class FeedbackAnalysis(BaseModel):
    """Structured output for feedback analysis."""
    issues: List[str] = Field(
        default_factory=list,
        description="List of issues found (e.g., 'wrong_info', 'misunderstood')"
    )
    corrected_response: str = Field(
        description="The corrected response that addresses the user's feedback"
    )
    lesson: str = Field(
        description="One sentence describing what was learned"
    )
    key_correction: str = Field(
        description="The single most important piece of corrected information (e.g., 'user name is Mansingh')"
    )


def clean_thinking_text(raw_text: str) -> str:
    """
    Clean raw LLM thinking text by removing markdown labels and troubleshooting URLs.
    
    Strips:
    - **thinking:** prefix
    - **thinking_steps:** prefix  
    - **answer:** section and everything after
    - Troubleshooting URLs (https://docs.langchain.com/...)
    
    Keeps: The actual reasoning content only.
    """
    if not raw_text:
        return ""
    
    cleaned = raw_text
    
    # Remove troubleshooting URL line
    if "For troubleshooting" in cleaned:
        cleaned = cleaned.split("For troubleshooting")[0]
    if "https://docs.langchain.com" in cleaned:
        # Remove from URL to end of line
        lines = cleaned.split('\n')
        lines = [l for l in lines if "https://docs.langchain.com" not in l]
        cleaned = '\n'.join(lines)
    
    # Remove **answer:** section and everything after it
    if "**answer:**" in cleaned:
        cleaned = cleaned.split("**answer:**")[0]
    
    # Remove markdown labels (keep the content after them)
    cleaned = cleaned.replace("**thinking:**", "")
    cleaned = cleaned.replace("**thinking_steps:**", "")
    
    # Clean up extra whitespace
    lines = [line.strip() for line in cleaned.strip().split('\n') if line.strip()]
    cleaned = '\n'.join(lines)
    
    return cleaned


def _filter_messages_by_selection(messages, selected_indices):
    """Keep only selected conversation turns + the current (last) turn.

    A turn = one HumanMessage + all following AI/Tool messages until next HumanMessage.
    selected_indices: 0-based indices of user turns to include (from frontend).
    Empty list → return all messages unchanged.
    """
    if not selected_indices:
        return messages

    selected_set = set(selected_indices)
    turns = []
    current_turn = []

    for msg in messages:
        if isinstance(msg, HumanMessage) and current_turn:
            turns.append(current_turn)
            current_turn = [msg]
        else:
            current_turn.append(msg)
    if current_turn:
        turns.append(current_turn)

    filtered = []
    for i, turn in enumerate(turns):
        if i == len(turns) - 1 or i in selected_set:
            filtered.extend(turn)

    return filtered


async def agent_node(
    state: AgentState,
    llm_with_tools: Any,
) -> Dict[str, Any]:
    """
    Main agent reasoning node (Day 4 Enhanced).

    Takes the current state and generates a response,
    potentially including tool calls.
    Now includes learned lessons in context.
    """
    print("[AGENT_NODE] Starting...")
    messages = state["messages"]
    print(f"[AGENT_NODE] Messages count: {len(messages)}")

    # Apply context selection filter if user has pinned specific turns
    selected_indices = state.get("selected_message_indices") or []
    if selected_indices:
        messages = _filter_messages_by_selection(list(messages), selected_indices)
        print(f"[AGENT_NODE] Context filter active: {len(messages)} msgs kept (selected turns: {selected_indices})")

    # ═══════════════════════════════════════════════════════════════════════
    # BUILD CONTEXT FROM MEMORIES AND LESSONS (Day 4)
    # ═══════════════════════════════════════════════════════════════════════
    memory_context = ""
    lessons_context = ""

    if state.get("relevant_memories"):
        for mem in state["relevant_memories"][:7]:
            mem_type = mem.get("type", "unknown")

            if mem_type == "learned_lesson":
                # Day 4: Include learned lessons with improved approach
                lessons_context += f"\n- LEARNED: {mem.get('content', '')}"
                if mem.get("improved_approach"):
                    lessons_context += f" → DO: {mem.get('improved_approach')}"

            elif mem_type == "error_lesson":
                # Error-specific lessons (higher priority)
                lessons_context += f"\n- FIX: {mem.get('content', '')}"

            elif mem_type == "prompt_improvement":
                # Superhuman memory: past corrections from negative feedback
                # Extract key correction for direct application
                key_correction = mem.get('key_correction', '')
                user_feedback = mem.get('user_feedback', mem.get('content', ''))

                if key_correction:
                    # Strong, direct instruction with the key fact
                    lessons_context += f"\n- ⚠️ CRITICAL OVERRIDE: {key_correction}. This is a verified correction from the user - USE THIS, do not ask again."
                else:
                    # Fallback to user feedback extraction
                    lessons_context += f"\n- ⚠️ USER CORRECTION: The user previously corrected you: '{user_feedback[:150]}'. Apply this correction directly."

                print(f"[AGENT_NODE] 🧠 Applying past correction: {key_correction or user_feedback[:80]}...")

            elif mem_type == "matched_skill":
                # Day 5: Matched skill from skill library
                skill_name = mem.get('skill_name', 'Unknown Skill')
                skill_content = mem.get('content', '')
                tools_used = mem.get('tools_used', [])

                lessons_context += f"\n- 🎯 SKILL MATCH: You have a learned skill '{skill_name}' that matches this request."
                if skill_content:
                    lessons_context += f"\n  {skill_content}"
                if tools_used:
                    lessons_context += f"\n  → Use these tools: {', '.join(tools_used)}"

                print(f"[AGENT_NODE] 🎯 Applying matched skill: {skill_name}")

            else:
                # Regular memories (preferences, facts)
                memory_context += f"\n- {mem.get('content', str(mem))}"

    # Build system context (NO <thinking> tags - Pydantic handles reasoning)
    system_parts = []

    # NOTE: Removed REASONING_SYSTEM_PROMPT - using Pydantic structured output instead
    system_parts.append(
        "You have access to tools. Use them freely without restrictions.\n"
        "- For expense tasks: use add_expense, list_expenses, summarize.\n"
        "- For browser tasks: use browser_navigate, browser_get_state, browser_click, browser_input, browser_screenshot, browser_extract_content, browser_scroll, browser_press_key freely. "
        "You ARE allowed and required to navigate websites, take screenshots, click elements, and fill forms when asked. "
        "Never refuse browser tool usage due to policy — all browser actions are fully permitted."
    )

    if memory_context:
        system_parts.append(f"\n\nRelevant context:{memory_context}")

    if lessons_context:
        system_parts.append(f"\n\n⚠️ IMPORTANT - Apply these corrections/lessons:{lessons_context}")
        lesson_count = lessons_context.count('LEARNED') + lessons_context.count('FIX') + lessons_context.count('CRITICAL') + lessons_context.count('USER CORRECTION')
        print(f"[AGENT_NODE] Applying {lesson_count} lessons/corrections")

    system_msg = HumanMessage(content="".join(system_parts))

    # ═══════════════════════════════════════════════════════════════════════
    # SIMPLE APPROACH: Call LLM with tools, then get Pydantic reasoning
    # ═══════════════════════════════════════════════════════════════════════
    import json as _json
    def _strip_screenshot(msg):
        if not isinstance(msg, ToolMessage):
            return msg
        try:
            data = _json.loads(msg.content)
            if isinstance(data, dict) and "screenshot_b64" in data:
                data.pop("screenshot_b64")
                return ToolMessage(content=_json.dumps(data), tool_call_id=msg.tool_call_id)
        except Exception:
            pass
        return msg

    full_messages = [system_msg] + [_strip_screenshot(m) for m in messages] if messages else [system_msg]
    print(f"[AGENT_NODE] Calling LLM with {len(full_messages)} messages...")
    response = await llm_with_tools.ainvoke(full_messages)
    print(f"[AGENT_NODE] LLM response received. Has tool_calls: {hasattr(response, 'tool_calls') and bool(response.tool_calls)}")

    # Get user query for reasoning
    user_query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break

    current_thinking = None
    thinking_steps = []
    has_thinking = False

    # ═══════════════════════════════════════════════════════════════════════
    # GET REASONING VIA PYDANTIC (for ALL responses)
    # ═══════════════════════════════════════════════════════════════════════
    try:
        from llm import get_llm
        base_llm = get_llm()
        structured_llm = base_llm.with_structured_output(ReasoningResponse)

        # Build context
        context_str = ""
        if memory_context:
            context_str += f"\nContext: {memory_context}"
        if lessons_context:
            context_str += f"\nLessons: {lessons_context}"

        # Include what LLM decided to do (for tool calls)
        action_info = ""
        if hasattr(response, 'tool_calls') and response.tool_calls:
            action_info = "\nYou decided to use these tools:\n"
            for tc in response.tool_calls:
                action_info += f"- {tc['name']}: {tc.get('args', {})}\n"

        reasoning_prompt = f"""Explain your reasoning for this request:

User's request: {user_query}
{context_str}
{action_info}

Provide your step-by-step thinking:
1. thinking: Your detailed reasoning process
2. thinking_steps: List of individual steps (e.g., ["1. User wants X", "2. I need to Y"])
3. answer: A brief summary of what you're doing (or your response if no tools used)"""

        reasoning_result = await structured_llm.ainvoke([HumanMessage(content=reasoning_prompt)])

        current_thinking = reasoning_result.thinking
        thinking_steps = reasoning_result.thinking_steps
        has_thinking = True

        print(f"[AGENT_NODE] 🧠 Pydantic reasoning: {len(thinking_steps)} steps")
        for i, step in enumerate(thinking_steps[:3], 1):
            print(f"[AGENT_NODE]   Step {i}: {step[:60]}...")

    except Exception as e:
        print(f"[AGENT_NODE] ⚠️ Pydantic reasoning failed: {e}")
        # Ollama returns text, not JSON - just use the raw text as thinking
        error_str = str(e)
        # Remove "Invalid json output:" prefix if present
        if "Invalid json output:" in error_str:
            raw_thinking = error_str.replace("Invalid json output:", "").strip()
        else:
            raw_thinking = error_str

        if raw_thinking and len(raw_thinking) > 10:
            # Clean the thinking text - remove markdown labels and URLs
            current_thinking = clean_thinking_text(raw_thinking)
            # Split by newlines for steps (simple, no regex)
            lines = [line.strip() for line in current_thinking.split('\n') if line.strip()]
            thinking_steps = lines[:10]  # First 10 lines as steps
            has_thinking = True
            print(f"[AGENT_NODE] 🧠 Using cleaned LLM thinking: {len(thinking_steps)} lines")

    # Update state
    updates = {
        "messages": [response],
        "status": AgentStatus.THINKING,
        "updated_at": datetime.utcnow().isoformat(),
        "turn_count": state.get("turn_count", 0) + 1,
        # Day 5.5: Thinking/Reasoning
        "current_thinking": current_thinking,
        "thinking_steps": thinking_steps,
        "has_thinking": has_thinking,
    }

    # Check for tool calls
    if hasattr(response, "tool_calls") and response.tool_calls:
        print(f"[AGENT_NODE] Tool calls detected: {[tc['name'] for tc in response.tool_calls]}")
        # Reasoning already derived from actual tool decisions above

        updates["pending_tool_calls"] = [
            {
                "id": tc["id"],
                "name": tc["name"],
                "args": tc["args"],
                "status": "pending",
            }
            for tc in response.tool_calls
        ]
        updates["status"] = AgentStatus.EXECUTING_TOOL
    else:
        print(f"[AGENT_NODE] No tool calls, response content: {response.content[:100] if hasattr(response, 'content') else 'No content'}")

    print("[AGENT_NODE] Done")
    return updates


async def tool_execution_node(
    state: AgentState,
    tools: list,
    approval_gates: Any,
    interrupt_manager: Any,
) -> Dict[str, Any]:
    """
    Tool execution node with approval gates.

    NOTE: Approval is handled by LangGraph's interrupt_before=["tools"].
    This node only executes tools AFTER the graph resumes from interrupt.
    """
    print("[TOOL_NODE] Starting tool execution...")
    pending_calls = state.get("pending_tool_calls", [])
    if not pending_calls:
        print("[TOOL_NODE] No pending calls, returning completed")
        return {"status": AgentStatus.COMPLETED}

    tool_results = []
    tool_map = {tool.name: tool for tool in tools}

    for call in pending_calls:
        tool_name = call["name"]
        tool_args = call["args"]
        print(f"[TOOL_NODE] Executing tool: {tool_name} with args: {tool_args}")

        # Execute the tool directly - approval is already granted via LangGraph interrupt
        try:
            tool = tool_map.get(tool_name)
            if tool:
                result = await tool.ainvoke(tool_args)
                print(f"[TOOL_NODE] Tool result: {str(result)[:100]}...")
                tool_results.append({
                    "tool_call_id": call["id"],
                    "name": tool_name,
                    "result": result,
                    "status": "completed",
                })

                # Detect login page and emit credential_required via HITL
                if tool_name == "browser_get_state":
                    import json as _jj, re as _re
                    _state_str = result if isinstance(result, str) else _jj.dumps(result) if isinstance(result, dict) else str(result)
                    if "password" in _state_str.lower():
                        # Extract indexed fields from state text
                        _fields = []
                        # Find password field index
                        _pw = _re.search(r'\[?(\d+)\]?[^\n]*?(?:type=["\']?password|password)', _state_str, _re.IGNORECASE)
                        if _pw:
                            _pw_idx = int(_pw.group(1))
                            # Find text/email field just before password (index = pw_idx - 1 usually)
                            _un = _re.search(r'\[?(\d+)\]?[^\n]*?(?:type=["\']?(?:text|email)|username|email|user)', _state_str, _re.IGNORECASE)
                            _un_idx = int(_un.group(1)) if _un else _pw_idx - 1
                            # Find submit button
                            _sb = _re.search(r'\[?(\d+)\]?[^\n]*?(?:login|sign.?in|submit)', _state_str, _re.IGNORECASE)
                            _sb_idx = int(_sb.group(1)) if _sb else None
                            _fields = [
                                {"index": _un_idx, "label": "Username / Email", "type": "text"},
                                {"index": _pw_idx, "label": "Password", "type": "password"},
                            ]
                            _emit = ws_emit_var.get()
                            if _emit and _fields:
                                print(f"[TOOL_NODE] Login page detected — emitting credential_required")
                                await _emit({
                                    "type": "credential_required",
                                    "fields": _fields,
                                    "submit_index": _sb_idx,
                                })

                # Emit screenshot directly to UI (like reference retest_zap_executor.py)
                emit = ws_emit_var.get()
                if emit:
                    import json as _j
                    rd = result if isinstance(result, dict) else None
                    if rd is None and isinstance(result, str):
                        try:
                            rd = _j.loads(result)
                        except Exception:
                            pass
                    if isinstance(rd, dict) and rd.get("screenshot_b64"):
                        print(f"[TOOL_NODE] Emitting screenshot for {tool_name}")
                        await emit({
                            "type": "screenshot",
                            "screenshot_b64": rd["screenshot_b64"],
                            "url": rd.get("url", rd.get("current_url", "")),
                            "title": rd.get("title", tool_name),
                        })
            else:
                print(f"[TOOL_NODE] Tool not found: {tool_name}")
                tool_results.append({
                    "tool_call_id": call["id"],
                    "name": tool_name,
                    "error": f"Tool '{tool_name}' not found",
                    "status": "failed",
                })
        except Exception as e:
            print(f"[TOOL_NODE] Tool execution error: {e}")
            tool_results.append({
                "tool_call_id": call["id"],
                "name": tool_name,
                "error": str(e),
                "status": "failed",
            })



    # Create tool messages for the conversation
    tool_messages = [
        ToolMessage(
            content=str(r.get("result", r.get("error", ""))),
            tool_call_id=r["tool_call_id"],
        )
        for r in tool_results
    ]

    # Count errors for reflection routing
    error_count = sum(1 for r in tool_results if r.get("status") == "failed")
    last_error_type = None
    if error_count > 0:
        for r in tool_results:
            if r.get("status") == "failed":
                last_error_type = r.get("name")
                break
        print(f"[TOOL_NODE] {error_count} tool(s) failed - will trigger reflection")

    return {
        "messages": tool_messages,
        "tool_results": tool_results,
        "pending_tool_calls": [],
        "status": AgentStatus.THINKING,
        "last_tool_call": pending_calls[-1] if pending_calls else None,
        "error_count": error_count,
        "last_error_type": last_error_type,
    }


async def memory_retrieval_node(
    state: AgentState,
    memory_manager: Any,
    improvement_store: Any = None,
) -> Dict[str, Any]:
    """
    Memory retrieval node (Day 4 Enhanced).

    Retrieves relevant memories AND learned lessons for the current context.
    SMART: Only fetches lessons when context matches - not blindly every time.
    """
    user_id = state.get("user_id")

    # Get the last user message for context
    last_user_msg = None
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content
            break

    if not last_user_msg:
        return {}

    memories = []

    # ═══════════════════════════════════════════════════════════════════════
    # PART 1: Standard memory retrieval (Day 1)
    # ═══════════════════════════════════════════════════════════════════════
    if memory_manager and user_id:
        try:
            # User preferences
            prefs = await memory_manager.get_all_user_preferences(user_id)
            if prefs:
                memories.append({
                    "type": "preferences",
                    "content": f"User preferences: {prefs}"
                })

            # Relevant facts
            facts = await memory_manager.recall_facts(user_id, query=last_user_msg, limit=3)
            for fact in facts:
                memories.append({
                    "type": "fact",
                    "content": fact
                })
        except Exception as e:
            print(f"[MEMORY] Memory retrieval error: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PART 2: SMART Lesson Retrieval (Day 4)
    # Only fetch when context suggests tool/action usage
    # ═══════════════════════════════════════════════════════════════════════
    if improvement_store:
        should_fetch_lessons = _should_fetch_lessons(last_user_msg, state)

        if should_fetch_lessons:
            try:
                # Detect likely tool/error type from user message
                detected_context = _detect_context(last_user_msg)

                if detected_context:
                    print(f"[MEMORY] Smart fetch: detected context '{detected_context}'")

                    # Fetch relevant lessons (max 3, high confidence only)
                    lessons = await improvement_store.find_relevant_lessons(
                        context=last_user_msg,
                        error_type=detected_context,
                        limit=3,
                    )

                    # Only include high-confidence lessons (>0.4)
                    for lesson in lessons:
                        if lesson.get("confidence", 0) >= 0.4:
                            memories.append({
                                "type": "learned_lesson",
                                "content": f"Past learning: {lesson.get('lesson_learned', '')}",
                                "improved_approach": lesson.get("improved_approach", ""),
                                "confidence": lesson.get("confidence", 0),
                            })
                            print(f"[MEMORY] Added lesson: {lesson.get('lesson_learned', '')[:50]}...")

            except Exception as e:
                print(f"[MEMORY] Lesson retrieval error: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PART 3: Error-specific lessons (if there was a recent error)
    # ═══════════════════════════════════════════════════════════════════════
    if state.get("error_count", 0) > 0 and improvement_store:
        try:
            # Get lessons for the specific error that occurred
            last_error_type = state.get("last_error_type", "general")
            error_lessons = await improvement_store.find_relevant_lessons(
                context="",
                error_type=last_error_type,
                limit=2,
            )

            for lesson in error_lessons:
                if lesson.get("confidence", 0) >= 0.3:  # Lower threshold for error recovery
                    memories.append({
                        "type": "error_lesson",
                        "content": f"Previous error fix: {lesson.get('improved_approach', '')}",
                    })
        except:
            pass

    if memories:
        print(f"[MEMORY] Retrieved {len(memories)} memories/lessons")

    return {"relevant_memories": memories}


def _should_fetch_lessons(user_message: str, state: AgentState) -> bool:
    """
    SMART: Decide if we should fetch lessons from DB.

    Only fetch when:
    1. Message suggests tool usage (add, list, create, etc.)
    2. There was a recent error
    3. Message is similar to previous failed contexts
    """
    if not user_message:
        return False

    msg_lower = user_message.lower()

    # Keywords that suggest tool usage
    tool_keywords = [
        "add", "create", "insert", "save", "store",
        "list", "show", "get", "fetch", "find",
        "delete", "remove", "update", "edit", "modify",
        "expense", "summarize", "calculate", "run", "execute",
    ]

    # Check if message contains tool-related keywords
    for keyword in tool_keywords:
        if keyword in msg_lower:
            return True

    # Always fetch if there was a recent error
    if state.get("error_count", 0) > 0:
        return True

    # If retry was suggested, fetch lessons
    if state.get("retry_suggested"):
        return True

    return False


def _detect_context(user_message: str) -> str:
    """
    Detect the likely tool/action context from user message.

    Returns tool name or action type for targeted lesson search.
    """
    msg_lower = user_message.lower()

    # Map keywords to tool/context types
    context_map = {
        "expense": "add_expense",
        "add expense": "add_expense",
        "list expense": "list_expenses",
        "summarize": "summarize",
        "summary": "summarize",
        "execute": "execute_python",
        "run code": "execute_python",
        "python": "execute_python",
    }

    for keyword, context in context_map.items():
        if keyword in msg_lower:
            return context

    # Generic action detection
    if any(w in msg_lower for w in ["add", "create", "insert"]):
        return "create_action"
    if any(w in msg_lower for w in ["list", "show", "get"]):
        return "read_action"
    if any(w in msg_lower for w in ["delete", "remove"]):
        return "delete_action"

    return ""


async def memory_storage_node(
    state: AgentState,
    memory_manager: Any,
) -> Dict[str, Any]:
    """
    Memory storage node.

    Stores facts and patterns learned during the conversation.
    """
    facts_to_remember = state.get("facts_to_remember", [])
    user_id = state.get("user_id")

    if not user_id or not facts_to_remember:
        return {"facts_to_remember": []}

    for fact in facts_to_remember:
        await memory_manager.remember_fact(user_id, fact, source="conversation")

    return {"facts_to_remember": []}


async def reflection_node(
    state: AgentState,
    llm: Any,
    memory_manager: Any,
    reflection_system: Any = None,
) -> Dict[str, Any]:
    """
    Reflection node for self-improvement (Day 4).

    Uses the intelligence module to:
    1. Analyze failures deeply
    2. Generate lessons learned
    3. Store improvements in MongoDB
    4. Apply past lessons to future actions
    """
    last_tool = state.get("last_tool_call")
    tool_results = state.get("tool_results", [])

    if not last_tool or not tool_results:
        return {"should_reflect": False}

    # Find the result for the last tool call
    last_result = None
    for r in tool_results:
        if r.get("tool_call_id") == last_tool.get("id"):
            last_result = r
            break

    if not last_result:
        return {"should_reflect": False}

    # Determine if reflection is needed
    is_failure = last_result.get("status") == "failed"
    has_errors = state.get("error_count", 0) > 0

    if not (is_failure or has_errors):
        # On success, optionally record success pattern
        if reflection_system and last_result.get("status") == "completed":
            try:
                await reflection_system.reflect_on_success(
                    actions=[last_tool],
                    outcome=str(last_result.get("result", ""))[:200],
                    context=state.get("thread_id", "unknown"),
                )
            except:
                pass
        return {"should_reflect": False}

    # ═══════════════════════════════════════════════════════════════════════
    # USE INTELLIGENCE MODULE FOR DEEP REFLECTION
    # ═══════════════════════════════════════════════════════════════════════

    print(f"[REFLECT] Reflecting on failed action: {last_tool.get('name')}")

    if reflection_system:
        # Use the new ReflectionSystem from core.intelligence
        try:
            action = {
                "type": "tool_call",
                "name": last_tool.get("name"),
                "args": last_tool.get("args"),
                "id": last_tool.get("id"),
            }

            error_msg = last_result.get("error", "Unknown error")
            context = f"Thread: {state.get('thread_id', 'unknown')}"

            # Get user message for context
            user_msg = None
            for msg in reversed(state.get("messages", [])):
                if isinstance(msg, HumanMessage):
                    user_msg = msg.content
                    break

            # Deep reflection with lesson generation
            result = await reflection_system.reflect_on_error(
                action=action,
                error=error_msg,
                context=context,
                user_message=user_msg,
            )

            print(f"[REFLECT] Lesson learned: {result.lesson_learned[:100]}...")
            print(f"[REFLECT] Should retry: {result.should_retry}")

            return {
                "should_reflect": False,
                "reflection_result": {
                    "action": last_tool.get("name"),
                    "lesson": result.lesson_learned,
                    "improved_approach": result.improved_approach,
                    "should_retry": result.should_retry,
                    "tags": result.tags,
                },
                # If should retry, the graph can route back to agent
                "retry_suggested": result.should_retry,
            }

        except Exception as e:
            print(f"[REFLECT] Reflection error: {e}")
            # Fall through to basic reflection

    # ═══════════════════════════════════════════════════════════════════════
    # FALLBACK: Basic reflection without intelligence module
    # ═══════════════════════════════════════════════════════════════════════

    reflection_prompt = f"""
    Reflect on this action:

    Action: {last_tool.get('name')}
    Arguments: {last_tool.get('args')}
    Result: {last_result.get('result', last_result.get('error'))}
    Success: {last_result.get('status') == 'completed'}

    Analyze:
    1. Was this action successful?
    2. What went wrong (if anything)?
    3. What should be done differently next time?

    Provide a brief lesson learned.
    """

    reflection_response = await llm.ainvoke([HumanMessage(content=reflection_prompt)])
    lesson = reflection_response.content if hasattr(reflection_response, 'content') else str(reflection_response)

    # Store in memory manager if available
    if memory_manager and state.get("user_id"):
        try:
            await memory_manager.save_error_lesson(
                error_type=last_tool.get("name", "unknown"),
                lesson={
                    "action": last_tool,
                    "result": last_result,
                    "lesson": lesson,
                }
            )
        except:
            pass

    return {
        "should_reflect": False,
        "reflection_result": {
            "action": last_tool.get("name"),
            "lesson": lesson,
        },
    }


async def interrupt_resume_node(
    state: AgentState,
    interrupt_manager: Any,
    tools: list,
) -> Dict[str, Any]:
    """
    Node to handle resuming after an interrupt.

    Called when human responds to an approval request.
    """
    interrupt_id = state.get("interrupt_id")
    if not interrupt_id:
        return {"awaiting_approval": False}

    # Get the interrupt response
    interrupt = await interrupt_manager.get_interrupt(interrupt_id)
    if not interrupt:
        return {
            "awaiting_approval": False,
            "interrupt_id": None,
        }

    status_val = interrupt.status if isinstance(interrupt.status, str) else interrupt.status.value
    if status_val == "pending":
        # Still waiting
        return {}

    interrupt_data = state.get("interrupt_data", {})
    tool_call = interrupt_data.get("tool_call")

    if status_val == "approved":
        # Execute the approved tool
        tool_map = {tool.name: tool for tool in tools}
        tool = tool_map.get(tool_call["name"])

        if tool:
            try:
                result = await tool.ainvoke(tool_call["args"])
                tool_message = ToolMessage(
                    content=str(result),
                    tool_call_id=tool_call["id"],
                )
                return {
                    "messages": [tool_message],
                    "tool_results": [{
                        "tool_call_id": tool_call["id"],
                        "name": tool_call["name"],
                        "result": result,
                        "status": "completed",
                    }],
                    "awaiting_approval": False,
                    "interrupt_id": None,
                    "interrupt_data": None,
                    "status": AgentStatus.THINKING,
                }
            except Exception as e:
                return {
                    "messages": [ToolMessage(
                        content=f"Error: {str(e)}",
                        tool_call_id=tool_call["id"],
                    )],
                    "awaiting_approval": False,
                    "interrupt_id": None,
                    "status": AgentStatus.ERROR,
                    "error_count": state.get("error_count", 0) + 1,
                }

    elif status_val == "rejected":
        # Tool was rejected
        return {
            "messages": [ToolMessage(
                content=f"Tool call '{tool_call['name']}' was rejected by user.",
                tool_call_id=tool_call["id"],
            )],
            "awaiting_approval": False,
            "interrupt_id": None,
            "interrupt_data": None,
            "status": AgentStatus.THINKING,
        }

    return {"awaiting_approval": False}


# ═══════════════════════════════════════════════════════════════════════════════
# FEEDBACK DETECTION AND PROCESSING (Day 4 - Prompt Improvements)
# ═══════════════════════════════════════════════════════════════════════════════

# Keywords indicating negative feedback
NEGATIVE_FEEDBACK_KEYWORDS = [
    # Direct negative
    "wrong", "incorrect", "bad", "terrible", "awful", "horrible",
    "no that's not", "that's not what", "not what i asked", "not what i wanted",
    # Correction indicators
    "actually", "i meant", "i wanted", "should be", "supposed to be",
    "fix this", "fix it", "correct this", "try again",
    # Dissatisfaction
    "doesn't work", "didn't work", "not working", "broken",
    "useless", "unhelpful", "not helpful",
    # Clarification with frustration
    "no no", "nope", "that's wrong", "you misunderstood",
    "i said", "what i said was", "listen",
]

# Keywords indicating positive feedback (to not confuse with negative)
POSITIVE_FEEDBACK_KEYWORDS = [
    "thanks", "thank you", "great", "perfect", "excellent", "good job",
    "that's right", "correct", "exactly", "yes that's it", "awesome",
]


def _extract_key_correction(feedback: str, original_prompt: str) -> str:
    """
    Extract the key corrected fact from user's feedback.

    Looks for patterns like:
    - "my name is X" → "User's name is X"
    - "it should be X" → "Correct answer is X"
    - "no, X" → "X"

    Returns a direct, factual statement for future use.
    """
    import re

    feedback_lower = feedback.lower()

    # Pattern: "my name is X" or "my real name is X"
    name_match = re.search(r"my\s+(?:real\s+)?(?:actual\s+)?name\s+is\s+[\"']?([^\"',\.!?]+)", feedback_lower)
    if name_match:
        name = name_match.group(1).strip().title()
        return f"User's name is {name}"

    # Pattern: "it's X" or "it is X" or "should be X"
    correction_match = re.search(r"(?:it'?s|it\s+is|should\s+be|supposed\s+to\s+be)\s+[\"']?([^\"',\.!?]+)", feedback_lower)
    if correction_match:
        correction = correction_match.group(1).strip()
        return f"Correct answer: {correction}"

    # Pattern: "no, X" or "wrong, X"
    no_match = re.search(r"(?:no|wrong|incorrect)[,\s]+(?:it'?s|my|the)?\s*([^\.!?]+)", feedback_lower)
    if no_match:
        correction = no_match.group(1).strip()
        if len(correction) > 5:  # Meaningful correction
            return f"User correction: {correction}"

    # Fallback: use the feedback itself (cleaned)
    # Remove negative keywords and use the rest
    clean_feedback = feedback
    for word in ["wrong", "incorrect", "no", "actually", "you are"]:
        clean_feedback = re.sub(rf"\b{word}\b", "", clean_feedback, flags=re.IGNORECASE)

    clean_feedback = clean_feedback.strip(" ,.-!?")
    if clean_feedback and len(clean_feedback) > 3:
        return f"User stated: {clean_feedback[:100]}"

    return f"User disagreed with response to: {original_prompt[:50]}"


def detect_negative_feedback(user_message: str) -> tuple[bool, str]:
    """
    Detect if user message contains negative feedback.

    Returns:
        tuple: (is_negative_feedback: bool, feedback_type: str)
    """
    if not user_message:
        return False, ""

    msg_lower = user_message.lower().strip()

    # First check if it's positive feedback (to avoid false positives)
    for keyword in POSITIVE_FEEDBACK_KEYWORDS:
        if keyword in msg_lower:
            return False, ""

    # Check for negative feedback patterns
    for keyword in NEGATIVE_FEEDBACK_KEYWORDS:
        if keyword in msg_lower:
            # Determine feedback type
            if any(w in msg_lower for w in ["wrong", "incorrect", "that's not"]):
                feedback_type = "wrong_response"
            elif any(w in msg_lower for w in ["fix", "correct", "try again"]):
                feedback_type = "correction_request"
            elif any(w in msg_lower for w in ["i meant", "i wanted", "should be"]):
                feedback_type = "clarification"
            elif any(w in msg_lower for w in ["doesn't work", "not working", "broken"]):
                feedback_type = "not_working"
            else:
                feedback_type = "general_negative"

            print(f"[FEEDBACK] Detected negative feedback: '{keyword}' → type={feedback_type}")
            return True, feedback_type

    return False, ""


async def feedback_processing_node(
    state: AgentState,
    llm: Any,
    improvement_store: Any,
) -> Dict[str, Any]:
    """
    Process user feedback and learn from it (Day 4).

    When user gives negative feedback:
    1. Get the original user prompt (before the bad response)
    2. Get the LLM response that user didn't like
    3. Get user's feedback message
    4. Ask LLM to generate an improved response
    5. Store the complete learning cycle in MongoDB

    This creates data in prompt_improvements collection.
    """
    if not improvement_store:
        print("[FEEDBACK] No improvement_store available, skipping")
        return {"feedback_processed": False}

    messages = state.get("messages", [])
    if len(messages) < 3:
        # Need at least: user_prompt, llm_response, user_feedback
        return {"feedback_processed": False}

    # Find the conversation context:
    # messages[-1] = current user message (the feedback)
    # messages[-2] = last AI response (the bad one)
    # messages[-3] = original user request

    # Get the feedback message
    feedback_msg = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            feedback_msg = msg.content
            break

    if not feedback_msg:
        return {"feedback_processed": False}

    # Check if this is actually negative feedback
    is_negative, feedback_type = detect_negative_feedback(feedback_msg)
    if not is_negative:
        return {"feedback_processed": False}

    print(f"[FEEDBACK] Processing negative feedback: {feedback_type}")

    # Find the original prompt and bad response
    original_user_prompt = None
    bad_llm_response = None

    # Walk backwards to find the AI response and the user request before it
    found_ai = False
    for msg in reversed(messages[:-1]):  # Exclude the feedback message itself
        if isinstance(msg, AIMessage) and not found_ai:
            bad_llm_response = msg.content if hasattr(msg, 'content') else str(msg)
            found_ai = True
        elif isinstance(msg, HumanMessage) and found_ai:
            original_user_prompt = msg.content
            break

    if not original_user_prompt or not bad_llm_response:
        print("[FEEDBACK] Could not find original prompt or bad response")
        return {"feedback_processed": False}

    print(f"[FEEDBACK] Original prompt: {original_user_prompt[:50]}...")
    print(f"[FEEDBACK] Bad response: {bad_llm_response[:50]}...")
    print(f"[FEEDBACK] User feedback: {feedback_msg[:50]}...")

    # ═══════════════════════════════════════════════════════════════════════
    # ASK LLM TO GENERATE AN IMPROVED RESPONSE (Using Pydantic Structured Output)
    # ═══════════════════════════════════════════════════════════════════════

    improvement_prompt = f"""Analyze this failed interaction and provide a structured correction.

**Original User Request:**
{original_user_prompt}

**Your Previous Response (which user didn't like):**
{bad_llm_response[:500]}

**User's Correction/Feedback:**
{feedback_msg}

Extract:
1. issues: List what went wrong (e.g., ["wrong_info", "misunderstood"])
2. corrected_response: The correct response that addresses user's feedback
3. lesson: One sentence about what you learned
4. key_correction: THE SINGLE MOST IMPORTANT FACT to remember (e.g., "User's name is Mansingh, not Pratyus")

IMPORTANT: The key_correction should be a direct, factual statement that can be applied immediately in future interactions."""

    try:
        # Try structured output with Pydantic first
        structured_llm = llm.with_structured_output(FeedbackAnalysis)

        try:
            analysis: FeedbackAnalysis = await structured_llm.ainvoke([HumanMessage(content=improvement_prompt)])

            issues = analysis.issues
            improved_response = analysis.corrected_response
            lesson = analysis.lesson
            key_correction = analysis.key_correction

            print(f"[FEEDBACK] ✓ Pydantic parsing successful")
            print(f"[FEEDBACK] Key correction: {key_correction}")

        except Exception as parse_error:
            # Fallback: Manual parsing if structured output fails
            print(f"[FEEDBACK] Pydantic parsing failed ({parse_error}), using fallback...")

            improved_result = await llm.ainvoke([HumanMessage(content=improvement_prompt)])
            improved_content = improved_result.content if hasattr(improved_result, 'content') else str(improved_result)

            # Simple extraction from user feedback
            issues = ["parsing_fallback"]
            improved_response = improved_content
            lesson = "Applied user correction"

            # Extract key correction directly from user's feedback
            # Look for patterns like "my name is X" or "it should be X"
            key_correction = _extract_key_correction(feedback_msg, original_user_prompt)

        # Extract context keywords for future matching
        context_keywords = improvement_store._extract_keywords(original_user_prompt)

        # ═══════════════════════════════════════════════════════════════════════
        # STORE IN MONGODB (with key_correction for direct application)
        # ═══════════════════════════════════════════════════════════════════════

        improvement_id = await improvement_store.store_feedback_improvement(
            original_user_prompt=original_user_prompt,
            original_llm_response=bad_llm_response,
            user_negative_feedback=feedback_msg,
            improved_llm_response=improved_response,
            context_keywords=context_keywords,
            thread_id=state["thread_id"],  # Thread-scoped learning
            feedback_type=feedback_type,
            issues_detected=issues,
            key_correction=key_correction,  # NEW: Direct fact to apply
        )

        print(f"[FEEDBACK] Stored improvement: {improvement_id}")
        print(f"[FEEDBACK] Key correction: {key_correction}")
        print(f"[FEEDBACK] Issues: {issues}")

        return {
            "feedback_processed": True,
            "feedback_improvement": {
                "id": improvement_id,
                "original_prompt": original_user_prompt[:100],
                "feedback_type": feedback_type,
                "issues": issues,
                "key_correction": key_correction,
                "lesson": lesson,
            },
        }

    except Exception as e:
        print(f"[FEEDBACK] Error generating improvement: {e}")
        import traceback
        traceback.print_exc()
        return {"feedback_processed": False, "feedback_error": str(e)}


async def check_for_improvements_node(
    state: AgentState,
    improvement_store: Any,
) -> Dict[str, Any]:
    """
    Check if there are relevant prompt improvements for the current request.

    SMART CACHING (superhuman):
    1. Check cache first (in-memory, instant)
    2. Only query DB on cache miss
    3. Update cache with results
    
    This is called before the agent node to retrieve past learnings.
    """
    if not improvement_store:
        return {}

    # Get the user message
    user_message = None
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    if not user_message:
        return {}

    # Check if this is feedback itself (don't retrieve for feedback messages)
    is_negative, _ = detect_negative_feedback(user_message)
    if is_negative:
        return {"is_feedback_message": True}

    thread_id = state["thread_id"]
    cache = state.get("feedback_cache", [])

    # ═════════════════════════════════════════════════════════════════════
    # SMART CACHE CHECK (superhuman: instant retrieval)
    # ═════════════════════════════════════════════════════════════════════
    
    if cache and improvement_store.embedding_model:
        print("[IMPROVEMENTS] Checking cache...")
        
        # Generate embedding for current query
        query_embedding = improvement_store._generate_embedding(user_message)
        
        if query_embedding:
            # Check cache similarity
            for cached_imp in cache:
                cached_embedding = cached_imp.get("embedding")
                if cached_embedding:
                    similarity = improvement_store._cosine_similarity(query_embedding, cached_embedding)
                    
                    # Cache hit! (high similarity threshold for cache)
                    if similarity >= 0.75:
                        print(f"[IMPROVEMENTS] 🚀 CACHE HIT! Similarity: {similarity:.3f}")

                        # Get key_correction for direct application
                        key_correction = cached_imp.get('key_correction', '')
                        user_feedback = cached_imp.get('user_negative_feedback', '')

                        print(f"[IMPROVEMENTS] Key correction: {key_correction or 'None'}")

                        # Return cached improvement with key_correction
                        improvement_memories = [{
                            "type": "prompt_improvement",
                            "key_correction": key_correction,  # Direct fact to apply
                            "user_feedback": user_feedback,
                            "content": user_feedback,  # Fallback content
                            "original_request": cached_imp.get("original_user_prompt", ""),
                            "confidence": cached_imp.get("confidence", 0.5),
                            "from_cache": True,
                        }]

                        existing = state.get("relevant_memories", [])
                        return {"relevant_memories": existing + improvement_memories}

    # ═════════════════════════════════════════════════════════════════════
    # CACHE MISS: Query database with semantic search
    # ═════════════════════════════════════════════════════════════════════
    
    try:
        print("[IMPROVEMENTS] Cache miss - querying database...")
        
        improvements = await improvement_store.find_relevant_improvements(
            user_prompt=user_message,
            thread_id=thread_id,  # Thread-scoped!
            limit=5,
        )

        if improvements:
            print(f"[IMPROVEMENTS] Found {len(improvements)} relevant past improvements")

            # Add to relevant memories with key_correction
            improvement_memories = []
            for imp in improvements:
                if imp.get("final_score", 0) >= 0.4:  # Filter by score
                    key_correction = imp.get('key_correction', '')
                    user_feedback = imp.get('user_negative_feedback', '')

                    print(f"[IMPROVEMENTS] Adding: key_correction={key_correction or 'None'}")

                    improvement_memories.append({
                        "type": "prompt_improvement",
                        "key_correction": key_correction,  # Direct fact to apply
                        "user_feedback": user_feedback,
                        "content": user_feedback,  # Fallback content
                        "original_request": imp.get("original_user_prompt", ""),
                        "confidence": imp.get("confidence", 0.5),
                        "similarity": imp.get("similarity", 0),
                        "from_cache": False,
                    })

            # Update cache: keep top 10 highest-scored improvements
            updated_cache = sorted(improvements, key=lambda x: x.get("final_score", 0), reverse=True)[:10]

            if improvement_memories:
                existing = state.get("relevant_memories", [])
                return {
                    "relevant_memories": existing + improvement_memories,
                    "feedback_cache": updated_cache,  # Update cache
                }
            else:
                return {"feedback_cache": updated_cache}

    except Exception as e:
        print(f"[IMPROVEMENTS] Error retrieving improvements: {e}")
        import traceback
        traceback.print_exc()

    return {}


# ═══════════════════════════════════════════════════════════════════════════════
# SKILL RETRIEVAL NODE (Day 5)
# ═══════════════════════════════════════════════════════════════════════════════

async def skill_retrieval_node(
    state: AgentState,
    skill_store: Any,
) -> Dict[str, Any]:
    """
    Skill retrieval node (Day 5).

    Checks if any stored skills match the current user query.
    Uses DUAL embedding search (query + description) for semantic matching.

    If a matching skill is found:
    - Adds skill context to relevant_memories for agent_node to use
    - Records skill usage for analytics

    Returns:
        Dict with matched_skill info if found, else empty dict
    """
    if not skill_store:
        return {}

    # Get the last user message
    last_user_msg = None
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content
            break

    if not last_user_msg:
        return {}

    try:
        # Search for matching skills using dual embedding
        matching_skills = await skill_store.find_matching_skills(
            user_query=last_user_msg,
            limit=2,
            similarity_threshold=0.70,  # High threshold for reliable matches
        )

        if matching_skills:
            top_skill = matching_skills[0]
            skill_name = top_skill.get("name", "Unknown Skill")
            skill_description = top_skill.get("description", "")
            workflow_steps = top_skill.get("workflow_steps", [])
            tools_used = top_skill.get("tools_used", [])
            combined_score = top_skill.get("combined_score", 0)

            print(f"[SKILL] ✓ Found matching skill: {skill_name}")
            print(f"[SKILL]   Score: {combined_score:.3f}")
            print(f"[SKILL]   Tools: {tools_used}")

            # Build skill context for agent_node
            skill_context = f"SKILL MATCH: '{skill_name}' - {skill_description}"
            if workflow_steps:
                skill_context += "\nWorkflow steps:"
                for step in workflow_steps[:5]:  # Limit to first 5 steps
                    step_num = step.get("step_number", "?")
                    step_desc = step.get("description", "")
                    tool_name = step.get("tool_name", "")
                    if tool_name:
                        skill_context += f"\n  {step_num}. Use {tool_name}: {step_desc}"
                    else:
                        skill_context += f"\n  {step_num}. {step_desc}"

            # Add to relevant memories for agent_node
            skill_memory = {
                "type": "matched_skill",
                "skill_id": top_skill.get("skill_id"),
                "skill_name": skill_name,
                "content": skill_context,
                "tools_used": tools_used,
                "confidence": combined_score,
                "original_query": top_skill.get("original_user_query", ""),
            }

            existing = state.get("relevant_memories", [])

            # Record skill usage for analytics
            await skill_store.record_skill_usage(
                skill_id=top_skill.get("skill_id"),
                conversation_id=state.get("thread_id", ""),
                was_successful=True,  # Assume success, can update later
                user_query=last_user_msg,
            )

            return {
                "relevant_memories": existing + [skill_memory],
                "matched_skill": {
                    "skill_id": top_skill.get("skill_id"),
                    "name": skill_name,
                    "score": combined_score,
                }
            }

        else:
            print("[SKILL] No matching skills found")

    except Exception as e:
        print(f"[SKILL] Error during skill retrieval: {e}")
        import traceback
        traceback.print_exc()

    return {}


def should_continue(state: AgentState) -> Literal["tools", "memory", "reflect", "interrupt", "end"]:
    """
    Routing function to determine the next node.
    """
    # Check if waiting for approval
    if state.get("awaiting_approval"):
        return "interrupt"

    # Check if there are pending tool calls
    if state.get("pending_tool_calls"):
        return "tools"

    # Check if reflection is needed
    if state.get("should_reflect"):
        return "reflect"

    # Check the last message
    messages = state.get("messages", [])
    if messages:
        last_message = messages[-1]

        # If AI message has tool calls, go to tools
        if isinstance(last_message, AIMessage):
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"

    return "end"
