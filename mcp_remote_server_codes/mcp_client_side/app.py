"""
AGI Agentic Chatbot - Main Application
======================================
FastAPI application with:
- MongoDB-backed conversation persistence
- Human-in-the-loop (HITL) approvals
- Time travel / state rewind
- Long-term memory across sessions
"""

import json
import uuid
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from langchain_core.messages import HumanMessage, AIMessage
import os

from config import HOST, PORT
from llm import get_llm_with_tools

# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL STATE
# ══════════════════════════════════════════════════════════════════════════════

# Core components
agent_graph = None
tools = []
mcp_client = None

# Memory components
checkpointer = None
memory_manager = None

# HITL components
interrupt_manager = None
approval_gates = None
time_travel_manager = None

# Sandbox components (Day 3)
sandbox_executor = None

# Intelligence components (Day 4)
improvement_store = None
reflection_system = None

# Skill Store (Day 5)
skill_store = None

# Active WebSocket connections (for sending interrupts)
active_connections: Dict[str, WebSocket] = {}

# MongoDB configuration
MONGODB_CONNECTION_STRING = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "First_mongoDB_database")


# ══════════════════════════════════════════════════════════════════════════════
# LIFESPAN - STARTUP & SHUTDOWN
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize all components on startup."""
    global agent_graph, tools, mcp_client
    global checkpointer, memory_manager
    global interrupt_manager, approval_gates, time_travel_manager
    global sandbox_executor
    global improvement_store, reflection_system
    global skill_store

    print("=" * 60)
    print("🚀 AGI Agentic Chatbot Starting Up...")
    print("=" * 60)

    # ──────────────────────────────────────────────────────────────────────────
    # Step 1: Initialize Memory Components (Day 1)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n📦 Initializing Memory Components...")
    try:
        from core.memory import get_checkpointer, get_memory_manager

        checkpointer = await get_checkpointer(
            MONGODB_CONNECTION_STRING,
            MONGODB_DATABASE
        )
        print("  ✓ MongoDB Checkpointer initialized")

        memory_manager = await get_memory_manager(
            MONGODB_CONNECTION_STRING,
            MONGODB_DATABASE
        )
        print("  ✓ Memory Manager initialized")

    except Exception as e:
        print(f"  ⚠ Memory initialization failed: {e}")
        print("  → Running with in-memory fallback")
        checkpointer = None
        memory_manager = None

    # ──────────────────────────────────────────────────────────────────────────
    # Step 2: Initialize HITL Components (Day 2)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n🛡️ Initializing HITL Components...")
    try:
        from core.hitl import (
            get_interrupt_manager,
            get_approval_gates,
            get_time_travel_manager,
        )

        interrupt_manager = await get_interrupt_manager(
            MONGODB_CONNECTION_STRING,
            MONGODB_DATABASE
        )
        print("  ✓ Interrupt Manager initialized")

        approval_gates = get_approval_gates()
        print("  ✓ Approval Gates initialized")

        if checkpointer:
            time_travel_manager = await get_time_travel_manager(
                MONGODB_CONNECTION_STRING,
                MONGODB_DATABASE
            )
            print("  ✓ Time Travel Manager initialized")

    except Exception as e:
        print(f"  ⚠ HITL initialization failed: {e}")
        import traceback
        traceback.print_exc()
        interrupt_manager = None
        approval_gates = None
        time_travel_manager = None

    # ──────────────────────────────────────────────────────────────────────────
    # Step 3: Initialize Sandbox (Day 3)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n🐳 Initializing Sandbox Executor...")
    try:
        from core.sandbox import get_code_runner

        sandbox_executor = await get_code_runner()
        if sandbox_executor._docker and sandbox_executor._docker.is_available:
            print("  ✓ Docker Sandbox ready")
        else:
            print("  ⚠ Docker unavailable - using subprocess fallback")

    except Exception as e:
        print(f"  ⚠ Sandbox initialization failed: {e}")
        sandbox_executor = None

    # ──────────────────────────────────────────────────────────────────────────
    # Step 4: Initialize Intelligence Module (Day 4)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n🧠 Initializing Intelligence Module...")
    try:
        from core.intelligence import get_improvement_store, get_skill_store

        improvement_store = await get_improvement_store(
            MONGODB_CONNECTION_STRING,
            MONGODB_DATABASE
        )
        print("  ✓ Improvement Store ready (lessons, patterns)")

        # Day 5: Skill Store for learned workflows
        skill_store = await get_skill_store(
            MONGODB_CONNECTION_STRING,
            MONGODB_DATABASE
        )
        print("  ✓ Skill Store ready (learned skills)")

    except Exception as e:
        print(f"  ⚠ Intelligence initialization failed: {e}")
        improvement_store = None
        skill_store = None

    # ──────────────────────────────────────────────────────────────────────────
    # Step 5: Load MCP Tools
    # ──────────────────────────────────────────────────────────────────────────
    print("\n🔧 Loading MCP Tools...")
    from mcp_client import load_mcp_config
    mcp_servers = load_mcp_config()

    if mcp_servers:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            mcp_client = MultiServerMCPClient(mcp_servers)
            tools = await mcp_client.get_tools()
            print(f"  ✓ Loaded {len(tools)} tools from MCP servers")
            for t in tools:
                desc = t.description[:50] if t.description else 'No description'
                print(f"    - {t.name}: {desc}...")

        except Exception as e:
            print(f"  ⚠ Error loading MCP tools: {e}")
            tools = []
    else:
        print("  → No MCP servers configured")
        tools = []

    # ──────────────────────────────────────────────────────────────────────────
    # Step 6: Create Agent Graph
    # ──────────────────────────────────────────────────────────────────────────
    print("\n🤖 Creating Agent Graph...")
    try:
        from graph import create_agentic_graph
        from llm import get_llm

        llm = get_llm()

        agent_graph = await create_agentic_graph(
            llm=llm,
            tools=tools,
            connection_string=MONGODB_CONNECTION_STRING,
            database_name=MONGODB_DATABASE,
            enable_memory=checkpointer is not None,
            enable_hitl=interrupt_manager is not None,
            enable_reflection=memory_manager is not None,
        )
        print("  ✓ Agentic Graph created with HITL support")

    except Exception as e:
        print(f"  ⚠ Advanced graph failed, using basic agent: {e}")
        import traceback
        traceback.print_exc()

        # Fallback to basic agent
        from agent import create_agent
        llm_with_tools = get_llm_with_tools(tools)
        agent_graph = create_agent(llm_with_tools, tools)
        print("  → Using basic agent without HITL")

    print("\n" + "=" * 60)
    print("✅ Startup Complete!")
    print("=" * 60 + "\n")

    yield

    # ──────────────────────────────────────────────────────────────────────────
    # Shutdown
    # ──────────────────────────────────────────────────────────────────────────
    print("\n🛑 Shutting down...")


# ══════════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="AGI Agentic Chatbot",
    description="Self-learning AI with memory, HITL, and time travel",
    lifespan=lifespan
)

# Static files
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Include API routers
try:
    from api import history_router
    app.include_router(history_router)
    print("📡 History API router included")
except ImportError as e:
    print(f"⚠ Could not load history router: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# REST ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    """Serve the main chat UI."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/tools")
async def list_tools():
    """Return list of available MCP tools."""
    return {
        "tools": [
            {"name": t.name, "description": t.description}
            for t in tools
        ]
    }


@app.get("/api/status")
async def get_status():
    """Return system status."""
    return {
        "status": "running",
        "components": {
            "agent": agent_graph is not None,
            "checkpointer": checkpointer is not None,
            "memory_manager": memory_manager is not None,
            "interrupt_manager": interrupt_manager is not None,
            "approval_gates": approval_gates is not None,
            "time_travel": time_travel_manager is not None,
            "sandbox": sandbox_executor is not None,
            "intelligence": improvement_store is not None,
        },
        "tools_count": len(tools),
        "active_connections": len(active_connections),
    }


@app.get("/api/learning/stats")
async def get_learning_stats():
    """Get agent's learning statistics (Day 4)."""
    if not improvement_store:
        raise HTTPException(status_code=503, detail="Intelligence module not available")

    stats = await improvement_store.get_learning_stats()
    return stats


@app.get("/api/learning/lessons")
async def get_recent_lessons(limit: int = 10):
    """Get recent lessons learned by the agent."""
    if not improvement_store:
        raise HTTPException(status_code=503, detail="Intelligence module not available")

    cursor = improvement_store.error_lessons.find({}).sort(
        "created_at", -1
    ).limit(limit)

    lessons = []
    async for doc in cursor:
        lessons.append({
            "id": doc.get("id"),
            "error_type": doc.get("error_type"),
            "lesson_learned": doc.get("lesson_learned"),
            "improved_approach": doc.get("improved_approach"),
            "confidence": doc.get("confidence"),
            "usage_count": doc.get("usage_count"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
        })

    return {"lessons": lessons}


@app.get("/api/learning/prompt-improvements")
async def get_prompt_improvements(limit: int = 10):
    """Get recent prompt improvements from user feedback."""
    if not improvement_store:
        raise HTTPException(status_code=503, detail="Intelligence module not available")

    cursor = improvement_store.prompt_improvements.find({}).sort(
        "created_at", -1
    ).limit(limit)

    improvements = []
    async for doc in cursor:
        improvements.append({
            "id": doc.get("id"),
            "feedback_type": doc.get("feedback_type"),
            "original_user_prompt": doc.get("original_user_prompt", "")[:100],
            "user_negative_feedback": doc.get("user_negative_feedback", "")[:100],
            "improved_llm_response": doc.get("improved_llm_response", "")[:200],
            "context_keywords": doc.get("context_keywords", []),
            "issues_detected": doc.get("issues_detected", []),
            "confidence": doc.get("confidence"),
            "usage_count": doc.get("usage_count"),
            "success_rate": doc.get("success_rate"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
        })

    return {"improvements": improvements}


@app.post("/api/feedback")
async def submit_feedback(request: dict):
    """
    Submit explicit feedback for a response.

    This endpoint allows the UI to send explicit thumbs up/down feedback
    which then gets processed and stored.
    """
    if not improvement_store:
        raise HTTPException(status_code=503, detail="Intelligence module not available")

    feedback_type = request.get("feedback_type", "negative")  # positive or negative
    original_prompt = request.get("original_prompt", "")
    llm_response = request.get("llm_response", "")
    user_feedback = request.get("user_feedback", "")
    thread_id = request.get("thread_id", "")

    if feedback_type == "positive":
        # For positive feedback, just track success
        # Find and update any relevant improvements
        try:
            improvements = await improvement_store.find_relevant_improvements(
                user_prompt=original_prompt,
                limit=1,
            )
            if improvements:
                await improvement_store.update_improvement_effectiveness(
                    improvements[0]["id"],
                    was_successful=True,
                )
                return {"success": True, "message": "Positive feedback recorded"}
        except Exception as e:
            print(f"[FEEDBACK API] Error recording positive feedback: {e}")

        return {"success": True, "message": "Positive feedback noted"}

    elif feedback_type == "negative":
        # For negative feedback, we need more context
        if not original_prompt or not llm_response:
            raise HTTPException(
                status_code=400,
                detail="Missing original_prompt or llm_response for negative feedback"
            )

        # Generate improved response using LLM with Pydantic structured output
        try:
            from llm import get_llm
            from langchain_core.messages import HumanMessage
            from pydantic import BaseModel, Field
            from typing import List
            import re

            llm = get_llm()

            # Pydantic model for structured parsing
            class FeedbackAnalysis(BaseModel):
                issues: List[str] = Field(default_factory=list)
                corrected_response: str = Field(default="")
                key_correction: str = Field(default="")

            improvement_prompt = f"""Analyze this failed interaction.

**Original Request:** {original_prompt}
**Your Previous Response:** {llm_response[:500]}
**User's Feedback:** {user_feedback or "User marked this as unhelpful"}

Extract:
1. issues: What went wrong (e.g., ["wrong_info"])
2. corrected_response: The correct response
3. key_correction: THE SINGLE MOST IMPORTANT FACT (e.g., "User's name is Pratyus")"""

            # Try Pydantic structured output first
            issues = []
            improved_response = ""
            key_correction = ""

            try:
                structured_llm = llm.with_structured_output(FeedbackAnalysis)
                analysis = await structured_llm.ainvoke([HumanMessage(content=improvement_prompt)])
                issues = analysis.issues
                improved_response = analysis.corrected_response
                key_correction = analysis.key_correction
                print(f"[FEEDBACK API] ✓ Pydantic parsing successful, key_correction: {key_correction}")

            except Exception as parse_err:
                print(f"[FEEDBACK API] Pydantic failed ({parse_err}), using fallback...")

                # Fallback: Extract key_correction from user feedback directly
                feedback_lower = (user_feedback or "").lower()

                # Pattern: "my name is X"
                name_match = re.search(r"my\s+(?:real\s+)?(?:actual\s+)?(?:original\s+)?name\s+is\s+[\"']?([^\"',\.!?]+)", feedback_lower)
                if name_match:
                    name = name_match.group(1).strip().title()
                    key_correction = f"User's name is {name}"
                else:
                    # Generic extraction
                    key_correction = f"User stated: {user_feedback[:100]}" if user_feedback else ""

                improved_response = f"Based on feedback: {user_feedback}"
                issues = ["fallback_extraction"]

                print(f"[FEEDBACK API] Fallback key_correction: {key_correction}")

            # Extract keywords
            keywords = improvement_store._extract_keywords(original_prompt)

            # Store the improvement WITH key_correction
            improvement_id = await improvement_store.store_feedback_improvement(
                original_user_prompt=original_prompt,
                original_llm_response=llm_response,
                user_negative_feedback=user_feedback or "User marked as unhelpful",
                improved_llm_response=improved_response,
                context_keywords=keywords,
                thread_id=request.get("thread_id", "global"),
                feedback_type="explicit_negative",
                issues_detected=issues,
                key_correction=key_correction,  # NOW INCLUDED!
            )

            return {
                "success": True,
                "improvement_id": improvement_id,
                "message": "Negative feedback processed and improvement stored",
                "key_correction": key_correction,
                "improved_response": improved_response[:200],
            }

        except Exception as e:
            print(f"[FEEDBACK API] Error processing negative feedback: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Error processing feedback: {str(e)}")

    return {"success": False, "message": "Unknown feedback type"}


@app.post("/api/sandbox/execute")
async def execute_code(request: dict):
    """Execute code in sandbox."""
    if not sandbox_executor:
        raise HTTPException(status_code=503, detail="Sandbox not available")

    code = request.get("code", "")
    language = request.get("language", "python")
    tier = request.get("tier", "standard")

    if not code:
        raise HTTPException(status_code=400, detail="No code provided")

    from core.sandbox import ExecutionTier

    exec_tier = ExecutionTier.STANDARD
    if tier in [t.value for t in ExecutionTier]:
        exec_tier = ExecutionTier(tier)

    result = await sandbox_executor.run(code, language=language, tier=exec_tier)

    return {
        "success": result.status.value == "success",
        "output": result.output,
        "error": result.error,
        "execution_time": result.execution_time,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SKILL RECORDING (Day 5)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/record-skill")
async def record_skill(request: dict):
    """
    Record a user-liked response as a reusable skill.

    Called when user clicks the like button and confirms skill recording.
    Sends the interaction to LLM for proper naming and formatting.
    """
    if not skill_store:
        raise HTTPException(status_code=503, detail="Skill Store not available")

    # Extract request data
    user_query = request.get("user_query", "")
    llm_response = request.get("llm_response", "")
    tool_calls = request.get("tool_calls", [])  # List of tool calls made
    conversation_id = request.get("conversation_id", "")
    user_id = request.get("user_id", "default")
    # Day 5.5: Reasoning/Thinking data
    reasoning_steps = request.get("reasoning_steps", [])
    reasoning_raw = request.get("reasoning_raw", "")

    print(f"[SKILL API] Received request:")
    print(f"  → user_query: {user_query[:50]}...")
    print(f"  → reasoning_steps: {len(reasoning_steps)} steps")
    print(f"  → reasoning_raw: {len(reasoning_raw)} chars")

    if not user_query or not llm_response:
        raise HTTPException(
            status_code=400,
            detail="Missing user_query or llm_response"
        )

    # Filter: Only record skills with tool calls or multi-step reasoning
    has_tools = len(tool_calls) > 0
    is_multi_step = len(llm_response) > 200  # Basic heuristic

    if not has_tools and not is_multi_step:
        return {
            "success": False,
            "message": "This response is too simple to record as a skill. Skills should involve tool usage or complex reasoning.",
            "should_record": False
        }

    try:
        from llm import get_llm
        from langchain_core.messages import HumanMessage
        from pydantic import BaseModel, Field
        from typing import List

        llm = get_llm()

        # Pydantic model for skill formatting
        class SkillFormat(BaseModel):
            name: str = Field(description="Short, descriptive skill name (3-6 words)")
            description: str = Field(description="Clear description of what this skill does and when to use it")
            skill_type: str = Field(description="Type: tool_workflow, reasoning, hybrid, or multi_step")
            workflow_steps: List[dict] = Field(description="List of steps with step_number, action_type, tool_name (if any), description")

        # Build tool info for prompt
        tool_info = ""
        tools_used = []
        if tool_calls:
            tool_info = "\n**Tools Used:**\n"
            for tc in tool_calls:
                tool_name = tc.get("name", tc.get("tool", "unknown"))
                tool_args = tc.get("args", tc.get("arguments", {}))
                tools_used.append(tool_name)
                tool_info += f"- {tool_name}: {tool_args}\n"

        # Build reasoning info for prompt (Day 5.5)
        reasoning_info = ""
        if reasoning_steps and len(reasoning_steps) > 0:
            reasoning_info = "\n**AI's Reasoning Process:**\n"
            for step in reasoning_steps[:5]:  # Include up to 5 steps
                reasoning_info += f"- {step}\n"
        elif reasoning_raw:
            reasoning_info = f"\n**AI's Reasoning:**\n{reasoning_raw[:500]}\n"

        # Ask LLM to format the skill
        format_prompt = f"""You are creating a skill entry for an AI assistant's skill library.

**User's Original Query:**
{user_query}

**AI's Response:**
{llm_response[:1000]}
{tool_info}
{reasoning_info}

Create a structured skill entry. You MUST respond with ONLY valid JSON (no markdown, no explanation):

{{
  "name": "Short action-oriented name (3-6 words)",
  "description": "Detailed description explaining WHAT this skill does, HOW it works, and WHEN to use it. Include key phrases for semantic matching.",
  "skill_type": "tool_workflow OR reasoning OR hybrid OR multi_step",
  "workflow_steps": [
    {{"step_number": 1, "action_type": "tool_call OR reasoning OR confirmation", "tool_name": "tool_name or null", "description": "What this step does"}}
  ]
}}

RULES:
- name: Action-oriented (e.g., "Summarize Monthly Expenses", "Track Daily Spending")
- description: MUST be detailed (50-150 words) explaining the skill's purpose, capabilities, and use cases
- skill_type: "tool_workflow" if uses tools, "reasoning" if pure logic, "hybrid" if both, "multi_step" if sequential
- workflow_steps: Include ALL steps from the reasoning process

RESPOND WITH ONLY THE JSON OBJECT. NO MARKDOWN. NO BACKTICKS. NO EXPLANATION."""

        try:
            structured_llm = llm.with_structured_output(SkillFormat)
            skill_format: SkillFormat = await structured_llm.ainvoke([HumanMessage(content=format_prompt)])

            skill_name = skill_format.name
            skill_description = skill_format.description
            skill_type = skill_format.skill_type
            workflow_steps = skill_format.workflow_steps

            print(f"[SKILL API] ✓ LLM formatted skill: {skill_name}")

        except Exception as format_err:
            print(f"[SKILL API] Pydantic structured output failed: {format_err}")
            print(f"[SKILL API] Attempting direct LLM call with JSON parsing...")

            # Fallback: Try direct LLM call and parse JSON manually
            try:
                import json
                import re

                direct_response = await llm.ainvoke([HumanMessage(content=format_prompt)])
                response_text = direct_response.content if hasattr(direct_response, 'content') else str(direct_response)
                print(f"[SKILL API] Direct LLM response: {response_text[:300]}...")

                # Try to extract JSON from response
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    json_str = json_match.group(0)
                    parsed = json.loads(json_str)
                    skill_name = parsed.get("name", f"Skill: {user_query[:25]}...")
                    skill_description = parsed.get("description", f"Handles: {user_query}")
                    skill_type = parsed.get("skill_type", "tool_workflow" if tools_used else "reasoning")
                    workflow_steps = parsed.get("workflow_steps", [])
                    print(f"[SKILL API] ✓ JSON parsed from direct response: {skill_name}")
                else:
                    # Extract from markdown patterns
                    name_match = re.search(r'(?:name|Name|skill_name)["\s:]+([^\n"]+)', response_text)
                    desc_match = re.search(r'(?:description|Description)["\s:]+([^\n"]+)', response_text)

                    skill_name = name_match.group(1).strip().strip('",:') if name_match else f"Skill: {user_query[:25]}..."
                    skill_description = desc_match.group(1).strip().strip('",:') if desc_match else f"Handles requests like: {user_query}. {llm_response[:200]}"
                    skill_type = "tool_workflow" if tools_used else "reasoning"
                    workflow_steps = []
                    print(f"[SKILL API] ✓ Extracted from markdown: {skill_name}")

            except Exception as fallback_err:
                print(f"[SKILL API] All parsing failed ({fallback_err}), using basic fallback...")
                # Ultimate fallback: Use user query + LLM response for description
                skill_name = f"Skill: {user_query[:30]}..."
                # Include actual LLM response in description for better context
                skill_description = f"Handles requests like: {user_query}. This skill {llm_response[:300]}..."
                skill_type = "tool_workflow" if tools_used else "reasoning"
                workflow_steps = [
                    {
                        "step_number": 1,
                        "action_type": "tool_call" if tools_used else "reasoning",
                        "tool_name": tools_used[0] if tools_used else None,
                        "description": f"Execute {tools_used[0] if tools_used else 'reasoning'} based on user request"
                    }
                ]

        # Store the skill
        print(f"[SKILL API] 📝 Storing skill with {len(reasoning_steps)} reasoning steps")
        print(f"[SKILL API] 📝 Description: {skill_description[:100]}...")
        skill_id = await skill_store.store_skill(
            name=skill_name,
            description=skill_description,
            skill_type=skill_type,
            original_user_query=user_query,
            llm_response=llm_response,
            workflow_steps=workflow_steps,
            tools_used=tools_used,
            conversation_id=conversation_id,
            user_id=user_id,
            # Day 5.5: Reasoning/Thinking
            reasoning_steps=reasoning_steps,
            reasoning_raw=reasoning_raw,
        )

        return {
            "success": True,
            "skill_id": skill_id,
            "skill_name": skill_name,
            "skill_description": skill_description,
            "skill_type": skill_type,
            "tools_used": tools_used,
            "reasoning_step_count": len(reasoning_steps),
            "message": f"Skill '{skill_name}' recorded successfully!"
        }

    except Exception as e:
        print(f"[SKILL API] Error recording skill: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error recording skill: {str(e)}")


@app.get("/api/skills")
async def get_skills(limit: int = 20):
    """Get list of recorded skills."""
    if not skill_store:
        raise HTTPException(status_code=503, detail="Skill Store not available")

    cursor = skill_store.learned_skills.find(
        {"is_active": True}
    ).sort("created_at", -1).limit(limit)

    skills = []
    async for doc in cursor:
        skills.append({
            "skill_id": doc.get("skill_id"),
            "name": doc.get("name"),
            "description": doc.get("description"),
            "skill_type": doc.get("skill_type"),
            "tools_used": doc.get("tools_used", []),
            "use_count": doc.get("use_count", 0),
            "success_rate": doc.get("success_rate", 1.0),
            "conversation_id": doc.get("conversation_id"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
        })

    return {"skills": skills}


@app.get("/api/skills/stats")
async def get_skill_stats():
    """Get skill library statistics."""
    if not skill_store:
        raise HTTPException(status_code=503, detail="Skill Store not available")

    stats = await skill_store.get_skill_stats()
    return stats


@app.post("/api/interrupt/{interrupt_id}/respond")
async def respond_to_interrupt(
    interrupt_id: str,
    response: dict
):
    """Respond to an interrupt (approve/reject)."""
    if not interrupt_manager:
        raise HTTPException(status_code=503, detail="Interrupt manager not available")

    status = response.get("status", "rejected")
    data = response.get("data", {})

    success = await interrupt_manager.respond_to_interrupt(
        interrupt_id,
        status,
        data
    )

    if success:
        return {"success": True, "message": f"Interrupt {status}"}
    else:
        raise HTTPException(status_code=404, detail="Interrupt not found")


# ══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: str):
    """WebSocket endpoint for chat communication with HITL support."""
    await websocket.accept()

    # Track connection
    active_connections[conversation_id] = websocket

    # Generate thread_id if not provided
    thread_id = conversation_id

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)

            message_type = message_data.get("type", "message")

            # ──────────────────────────────────────────────────────────────────
            # Handle different message types
            # ──────────────────────────────────────────────────────────────────

            if message_type == "message":
                # Regular chat message
                user_message = message_data.get("message", "")
                user_id = message_data.get("user_id", "default_user")
                selected_context_indices = message_data.get("selected_context_indices", [])

                if not user_message:
                    continue

                await stream_agent_response(
                    websocket=websocket,
                    thread_id=thread_id,
                    user_message=user_message,
                    user_id=user_id,
                    selected_context_indices=selected_context_indices,
                )

            elif message_type == "interrupt_response":
                # Response to an interrupt (approve/reject)
                interrupt_id = message_data.get("interrupt_id")
                status = message_data.get("status", "rejected")
                response_data = message_data.get("data", {})

                print(f"[WS] Received interrupt_response: id={interrupt_id}, status={status}")

                # Resume agent after approval (interrupt_id is thread_id in our case)
                if status == "approved":
                    print(f"[WS] Calling resume_after_interrupt for thread: {thread_id}")
                    await resume_after_interrupt(
                        websocket=websocket,
                        thread_id=thread_id,
                        interrupt_id=interrupt_id,
                    )

            elif message_type == "credential_response":
                # User submitted login credentials — fill fields and click submit
                credentials = message_data.get("credentials", {})  # {field_index: value}
                submit_index = message_data.get("submit_index")
                tool_map = {t.name: t for t in tools}
                input_tool = tool_map.get("browser_input")
                click_tool = tool_map.get("browser_click")
                screenshot_tool = tool_map.get("browser_screenshot")

                await websocket.send_json({"type": "start"})
                for field_index, value in credentials.items():
                    if input_tool and value:
                        print(f"[CRED] Filling index={field_index} value=***")
                        result = await input_tool.ainvoke({"index": int(field_index), "value": value, "press_enter": False})
                        # emit screenshot after each fill
                        import json as _cj
                        rd = result if isinstance(result, dict) else None
                        if rd is None and isinstance(result, str):
                            try: rd = _cj.loads(result)
                            except: pass
                        if isinstance(rd, dict) and rd.get("screenshot_b64"):
                            await websocket.send_json({"type": "screenshot", "screenshot_b64": rd["screenshot_b64"], "url": rd.get("url",""), "title": "Filling credentials"})

                if submit_index is not None and click_tool:
                    print(f"[CRED] Clicking submit index={submit_index}")
                    result = await click_tool.ainvoke({"index": int(submit_index)})
                    import json as _cj2
                    rd = result if isinstance(result, dict) else None
                    if rd is None and isinstance(result, str):
                        try: rd = _cj2.loads(result)
                        except: pass
                    if isinstance(rd, dict) and rd.get("screenshot_b64"):
                        await websocket.send_json({"type": "screenshot", "screenshot_b64": rd["screenshot_b64"], "url": rd.get("url",""), "title": "After login"})

                await websocket.send_json({"type": "token", "content": "Credentials submitted. Checking login result..."})
                await websocket.send_json({"type": "end"})

            elif message_type == "rewind":
                # Time travel - rewind to checkpoint
                checkpoint_id = message_data.get("checkpoint_id")
                if time_travel_manager and checkpoint_id:
                    result = await time_travel_manager.rewind_to(
                        thread_id,
                        checkpoint_id
                    )
                    await websocket.send_json({
                        "type": "rewind_result",
                        "success": result.success,
                        "message": result.message,
                        "checkpoint_id": result.checkpoint_id,
                    })

            elif message_type == "edit_from_checkpoint":
                # LangGraph native checkpoint resumption - same thread, resume from checkpoint
                user_message = message_data.get("message", "")
                checkpoint_id = message_data.get("checkpoint_id")
                user_id = message_data.get("user_id", "default_user")

                print(f"\n{'='*60}")
                print(f"[EDIT] Thread: {thread_id}")
                print(f"[EDIT] Resume from checkpoint: {checkpoint_id}")
                print(f"[EDIT] New message: {user_message[:80] if user_message else 'EMPTY'}...")
                print(f"{'='*60}\n")

                if not user_message:
                    continue

                try:
                    # Use LangGraph's native checkpoint resumption
                    await stream_agent_response(
                        websocket=websocket,
                        thread_id=thread_id,
                        user_message=user_message,
                        user_id=user_id,
                        checkpoint_id=checkpoint_id,  # This tells LangGraph to resume from here
                    )
                except Exception as e:
                    print(f"[EDIT] ERROR: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "type": "error",
                        "content": f"Edit failed: {str(e)}"
                    })

            elif message_type == "get_timeline":
                # Get conversation timeline
                if time_travel_manager:
                    snapshots = await time_travel_manager.get_timeline(
                        thread_id,
                        limit=message_data.get("limit", 50)
                    )
                    await websocket.send_json({
                        "type": "timeline",
                        "thread_id": thread_id,
                        "checkpoints": [
                            {
                                "checkpoint_id": s.checkpoint_id,
                                "created_at": s.created_at.isoformat(),
                                "message_count": len(s.messages),
                            }
                            for s in snapshots
                        ],
                    })

    except WebSocketDisconnect:
        print(f"Client disconnected: {conversation_id}")
    except Exception as e:
        print(f"WebSocket error: {e}")
        import traceback
        traceback.print_exc()
        try:
            await websocket.close()
        except:
            pass
    finally:
        # Remove from active connections
        active_connections.pop(conversation_id, None)


# ══════════════════════════════════════════════════════════════════════════════
# AGENT STREAMING
# ══════════════════════════════════════════════════════════════════════════════

async def stream_agent_response(
    websocket: WebSocket,
    thread_id: str,
    user_message: str,
    user_id: str = "default_user",
    checkpoint_id: str = None,
    selected_context_indices: list = None,
):
    """Stream agent response with HITL support.

    Args:
        checkpoint_id: If provided, this is an edit operation (currently just logs it).
    """
    global agent_graph

    if agent_graph is None:
        await websocket.send_json({
            "type": "error",
            "content": "Agent not initialized. Check your configuration."
        })
        return

    try:
        # Signal start of response
        await websocket.send_json({"type": "start"})

        # Prepare input
        input_state = {
            "messages": [HumanMessage(content=user_message)],
            "thread_id": thread_id,
            "user_id": user_id,
            "selected_message_indices": selected_context_indices or [],
        }

        # Config for checkpointing
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        # LangGraph native checkpoint resumption
        # When checkpoint_id is provided, LangGraph resumes from that state,
        # only seeing messages up to that checkpoint (like Claude edit)
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id
            print(f"[STREAM] Resume from checkpoint: {checkpoint_id}")
            print(f"[STREAM] LangGraph will only see messages up to this checkpoint")
        else:
            print(f"[STREAM] Normal message for thread: {thread_id}")

        full_response = ""
        current_interrupt_id = None

        # Bind WebSocket emit to context so tool_execution_node can push screenshots directly
        from graph.nodes import ws_emit_var
        ws_emit_var.set(websocket.send_json)

        # Stream the agent response
        print(f"[STREAM] Starting astream for thread {thread_id}")
        async for event in agent_graph.astream(input_state, config=config):
            print(f"[STREAM] Event received: {list(event.keys())}")

            # ──────────────────────────────────────────────────────────────────
            # Memory node output
            # ──────────────────────────────────────────────────────────────────
            if "memory" in event:
                memories = event["memory"].get("relevant_memories", [])
                if memories:
                    print(f"[STREAM] Sending memory_context")
                    await websocket.send_json({
                        "type": "memory_context",
                        "memories": memories[:5],
                    })

            # ──────────────────────────────────────────────────────────────────
            # Agent node output
            # ──────────────────────────────────────────────────────────────────
            if "agent" in event:
                agent_output = event["agent"]
                messages = agent_output.get("messages", [])
                print(f"[STREAM] Agent event - messages: {len(messages)}")

                # ══════════════════════════════════════════════════════════════
                # SEND THINKING FIRST (Day 5.5 - Chain of Thought)
                # ══════════════════════════════════════════════════════════════
                if agent_output.get("has_thinking"):
                    thinking_steps = agent_output.get("thinking_steps", [])
                    current_thinking = agent_output.get("current_thinking", "")

                    print(f"[STREAM] 🧠 Sending thinking: {len(thinking_steps)} steps")
                    await websocket.send_json({
                        "type": "thinking",
                        "content": current_thinking,
                        "steps": thinking_steps,
                        "step_count": len(thinking_steps),
                    })

                if messages:
                    last_message = messages[-1]

                    if isinstance(last_message, AIMessage):
                        # Check for tool calls
                        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                            print(f"[STREAM] Sending {len(last_message.tool_calls)} tool_call events")
                            for tool_call in last_message.tool_calls:
                                print(f"[STREAM] Tool call: {tool_call['name']}")
                                await websocket.send_json({
                                    "type": "tool_call",
                                    "tool": tool_call["name"],
                                    "args": tool_call["args"]
                                })
                        elif last_message.content:
                            # Stream the text content
                            content = last_message.content
                            full_response = content
                            print(f"[STREAM] Sending token: {content[:50]}...")
                            await websocket.send_json({
                                "type": "token",
                                "content": content
                            })

            # ──────────────────────────────────────────────────────────────────
            # Tools node output
            # ──────────────────────────────────────────────────────────────────
            if "tools" in event:
                tools_output = event["tools"]
                print(f"[STREAM] Tools event: {tools_output.keys()}")

                # Check if waiting for approval
                if tools_output.get("awaiting_approval"):
                    interrupt_data = tools_output.get("interrupt_data", {})
                    current_interrupt_id = tools_output.get("interrupt_id")

                    print(f"[STREAM] Sending approval_required")
                    await websocket.send_json({
                        "type": "approval_required",
                        "interrupt_id": current_interrupt_id,
                        "tool_call": interrupt_data.get("tool_call"),
                        "message": interrupt_data.get("check", {}).get("message"),
                        "risk_level": interrupt_data.get("check", {}).get("risk_level"),
                    })
                    # Don't continue until approval
                    return

                # Tool results
                tool_messages = tools_output.get("messages", [])
                print(f"[STREAM] Tool messages: {len(tool_messages)}")
                for tm in tool_messages:
                    print(f"[STREAM] Sending tool_result")
                    raw_content = str(tm.content) if hasattr(tm, 'content') else str(tm)
                    await websocket.send_json({
                        "type": "tool_result",
                        "content": raw_content[:500]
                    })

                # Extract screenshots from tool_results (original objects, more reliable than re-parsing strings)
                import json as _json
                for tr in tools_output.get("tool_results", []):
                    raw = tr.get("result", "")
                    rd = None
                    if isinstance(raw, dict):
                        rd = raw
                    elif isinstance(raw, str):
                        try:
                            rd = _json.loads(raw)
                        except Exception:
                            pass
                    if isinstance(rd, dict) and rd.get("screenshot_b64"):
                        print(f"[STREAM] Sending screenshot from tool: {tr.get('name')}")
                        await websocket.send_json({
                            "type": "screenshot",
                            "screenshot_b64": rd["screenshot_b64"],
                            "url": rd.get("url", rd.get("current_url", "")),
                            "title": rd.get("title", ""),
                        })

            # ──────────────────────────────────────────────────────────────────
            # Interrupt node output
            # ──────────────────────────────────────────────────────────────────
            if "interrupt" in event:
                interrupt_output = event["interrupt"]
                if interrupt_output.get("awaiting_approval"):
                    await websocket.send_json({
                        "type": "waiting_approval",
                        "interrupt_id": interrupt_output.get("interrupt_id"),
                    })

            # ──────────────────────────────────────────────────────────────────
            # Reflection node output
            # ──────────────────────────────────────────────────────────────────
            if "reflect" in event:
                reflection = event["reflect"].get("reflection_result", {})
                if reflection:
                    await websocket.send_json({
                        "type": "reflection",
                        "action": reflection.get("action"),
                        "lesson": reflection.get("lesson"),
                    })

            # ──────────────────────────────────────────────────────────────────
            # Store memory node output
            # ──────────────────────────────────────────────────────────────────
            if "store_memory" in event:
                await websocket.send_json({
                    "type": "memory_stored",
                })

            # ──────────────────────────────────────────────────────────────────
            # LangGraph interrupt (approval required)
            # ──────────────────────────────────────────────────────────────────
            if "__interrupt__" in event:
                print(f"[STREAM] Graph interrupted - tools require approval")
                # Get current state to find pending tool calls
                current_state = await agent_graph.aget_state(config)
                state_values = current_state.values if current_state else {}
                state_messages = state_values.get("messages", [])
                
                if state_messages:
                    last_state_msg = state_messages[-1]
                    if hasattr(last_state_msg, "tool_calls") and last_state_msg.tool_calls:
                        tool_call = last_state_msg.tool_calls[0]
                        print(f"[STREAM] Sending approval_required for {tool_call['name']}")
                        # Use thread_id as the interrupt identifier since we're using LangGraph's native interrupt
                        await websocket.send_json({
                            "type": "approval_required",
                            "interrupt_id": thread_id,  # Use thread_id so resume works
                            "tool_call": {
                                "id": tool_call.get("id", ""),
                                "name": tool_call["name"],
                                "args": tool_call["args"]
                            },
                            "message": f"Approve execution of {tool_call['name']}?",
                            "risk_level": "medium",
                        })
                        return  # Wait for user response
                
                print("[STREAM] No tool calls found in interrupt state")
                return

        # Signal end of response
        print(f"[STREAM] Sending end event")
        await websocket.send_json({"type": "end"})

    except Exception as e:
        print(f"Agent streaming error: {e}")
        import traceback
        traceback.print_exc()
        await websocket.send_json({
            "type": "error",
            "content": f"Error: {str(e)}"
        })


async def stream_agent_response_with_history(
    websocket: WebSocket,
    thread_id: str,
    user_message: str,
    prior_messages: list,
    user_id: str = "default_user",
):
    """Stream agent response with prior message history (for fork/edit).

    This creates a NEW conversation with only the prior_messages + new message.
    The AI won't remember anything after the fork point.
    """
    global agent_graph

    if agent_graph is None:
        await websocket.send_json({
            "type": "error",
            "content": "Agent not initialized."
        })
        return

    try:
        await websocket.send_json({"type": "start"})

        # Build message list: prior messages + new user message
        all_messages = list(prior_messages) + [HumanMessage(content=user_message)]

        print(f"[FORK] Total messages: {len(all_messages)} (prior: {len(prior_messages)} + 1 new)")

        input_state = {
            "messages": all_messages,
            "thread_id": thread_id,
            "user_id": user_id,
        }

        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        # Stream the response
        async for event in agent_graph.astream(input_state, config=config):
            if "agent" in event:
                agent_output = event["agent"]
                messages = agent_output.get("messages", [])
                if messages:
                    last_message = messages[-1]
                    if isinstance(last_message, AIMessage):
                        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                            for tool_call in last_message.tool_calls:
                                await websocket.send_json({
                                    "type": "tool_call",
                                    "tool": tool_call["name"],
                                    "args": tool_call["args"]
                                })
                        elif last_message.content:
                            await websocket.send_json({
                                "type": "token",
                                "content": last_message.content
                            })

            if "tools" in event:
                tool_messages = event["tools"].get("messages", [])
                for tm in tool_messages:
                    await websocket.send_json({
                        "type": "tool_result",
                        "content": str(tm.content)[:500] if hasattr(tm, 'content') else str(tm)[:500]
                    })

        await websocket.send_json({"type": "end"})

    except Exception as e:
        print(f"Fork streaming error: {e}")
        import traceback
        traceback.print_exc()
        await websocket.send_json({
            "type": "error",
            "content": f"Error: {str(e)}"
        })


async def resume_after_interrupt(
    websocket: WebSocket,
    thread_id: str,
    interrupt_id: str,
):
    """Resume agent execution after an interrupt is approved."""
    global agent_graph

    print(f"[RESUME] Starting resume for thread: {thread_id}, interrupt: {interrupt_id}")
    
    if agent_graph is None:
        print("[RESUME] ERROR: agent_graph is None!")
        return

    try:
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        # Bind WebSocket emit so tool_execution_node can push screenshots directly
        from graph.nodes import ws_emit_var
        ws_emit_var.set(websocket.send_json)

        print(f"[RESUME] Calling astream(None, config) to continue from interrupt...")

        # Continue execution from where it was interrupted
        async for event in agent_graph.astream(None, config=config):
            print(f"[RESUME] Event received: {list(event.keys())}")
            
            # Process events same as stream_agent_response
            if "agent" in event:
                messages = event["agent"].get("messages", [])
                print(f"[RESUME] Agent event - messages: {len(messages)}")
                if messages:
                    last_message = messages[-1]
                    if isinstance(last_message, AIMessage) and last_message.content:
                        print(f"[RESUME] Sending token: {last_message.content[:50]}...")
                        await websocket.send_json({
                            "type": "token",
                            "content": last_message.content
                        })

            if "tools" in event:
                tools_out = event["tools"]
                tool_messages = tools_out.get("messages", [])
                print(f"[RESUME] Tools event - messages: {len(tool_messages)}")
                for tm in tool_messages:
                    print(f"[RESUME] Sending tool_result")
                    raw_content = str(tm.content) if hasattr(tm, 'content') else str(tm)
                    await websocket.send_json({
                        "type": "tool_result",
                        "content": raw_content[:500]
                    })

                # Extract screenshots from tool_results directly
                import json as _json
                for tr in tools_out.get("tool_results", []):
                    raw = tr.get("result", "")
                    rd = None
                    if isinstance(raw, dict):
                        rd = raw
                    elif isinstance(raw, str):
                        try:
                            rd = _json.loads(raw)
                        except Exception:
                            pass
                    if isinstance(rd, dict) and rd.get("screenshot_b64"):
                        print(f"[RESUME] Sending screenshot from tool: {tr.get('name')}")
                        await websocket.send_json({
                            "type": "screenshot",
                            "screenshot_b64": rd["screenshot_b64"],
                            "url": rd.get("url", rd.get("current_url", "")),
                            "title": rd.get("title", ""),
                        })

            if "__interrupt__" in event:
                # Another tool needs approval — send approval_required to UI and wait
                current_state = await agent_graph.aget_state(config)
                state_values = current_state.values if current_state else {}
                state_messages = state_values.get("messages", [])
                if state_messages:
                    last_state_msg = state_messages[-1]
                    if hasattr(last_state_msg, "tool_calls") and last_state_msg.tool_calls:
                        tool_call = last_state_msg.tool_calls[0]
                        print(f"[RESUME] Sending approval_required for {tool_call['name']}")
                        await websocket.send_json({
                            "type": "approval_required",
                            "interrupt_id": thread_id,
                            "tool_call": {
                                "id": tool_call.get("id", ""),
                                "name": tool_call["name"],
                                "args": tool_call["args"]
                            },
                            "message": f"Approve execution of {tool_call['name']}?",
                            "risk_level": "medium",
                        })
                        return

        print(f"[RESUME] Stream complete, sending end")
        await websocket.send_json({"type": "end"})

    except Exception as e:
        import traceback
        print(f"Resume error: {e}")
        traceback.print_exc()
        await websocket.send_json({
            "type": "error",
            "content": f"Resume error: {str(e)}"
        })


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
