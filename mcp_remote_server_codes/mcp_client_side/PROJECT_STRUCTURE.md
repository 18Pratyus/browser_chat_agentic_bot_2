# Agentic Bot 2.0 - Project Structure

```
mcp_client_side/
├── app.py                      # FastAPI main application
├── config.py                   # Environment configuration
├── .env                        # Environment variables
│
├── core/                       # Core AGI modules
│   ├── __init__.py
│   │
│   ├── memory/                 # Day 1: Memory Architecture
│   │   ├── __init__.py
│   │   ├── checkpointer.py     # MongoDB checkpointer (short-term)
│   │   ├── store.py            # MongoDB store (long-term memory)
│   │   ├── embeddings.py       # Embedding functions for semantic search
│   │   └── manager.py          # Unified memory interface
│   │
│   ├── hitl/                   # Day 2: Human-in-the-Loop
│   │   ├── __init__.py
│   │   ├── interrupt.py        # Interrupt handler for approvals
│   │   ├── time_travel.py      # State history & rewind
│   │   └── approval_gates.py   # Critical action approvals
│   │
│   ├── sandbox/                # Day 3: Sandbox Execution
│   │   ├── __init__.py
│   │   ├── docker_executor.py  # Docker container management
│   │   └── code_runner.py      # Safe code execution
│   │
│   ├── intelligence/           # Day 4: Reflection & Self-Improvement
│   │   ├── __init__.py
│   │   ├── reflection.py       # Self-critique loops
│   │   ├── error_analyzer.py   # Learn from failures
│   │   └── prompt_optimizer.py # Rewrite prompts based on feedback
│   │
│   ├── skills/                 # Day 5: Skill Library
│   │   ├── __init__.py
│   │   ├── schema.py           # Skill data structure
│   │   ├── recorder.py         # Record workflows as skills
│   │   ├── library.py          # Skill storage and retrieval
│   │   └── executor.py         # Run saved skills
│   │
│   ├── synthesis/              # Day 6: Skill Synthesis (AGI Leap)
│   │   ├── __init__.py
│   │   ├── analyzer.py         # Find combinable skills
│   │   ├── composer.py         # Combine skills into new ones
│   │   └── suggester.py        # Proactive skill suggestions
│   │
│   ├── agents/                 # Day 7: Multi-Agent Orchestration
│   │   ├── __init__.py
│   │   ├── supervisor.py       # Supervisor agent
│   │   ├── specialists.py      # Research, Coder, Analyst agents
│   │   └── governance.py       # Security/governance agent
│   │
│   └── proactive/              # Day 8: Proactive Intelligence
│       ├── __init__.py
│       ├── pattern_detector.py # User pattern recognition
│       ├── goal_generator.py   # Autonomous goal generation
│       └── suggester.py        # Proactive suggestions
│
├── graph/                      # LangGraph definitions
│   ├── __init__.py
│   ├── agent_graph.py          # Main agent graph with HITL
│   ├── nodes.py                # Graph nodes (agent, tools, reflection)
│   └── state.py                # State definitions
│
├── api/                        # API routes
│   ├── __init__.py
│   ├── chat.py                 # WebSocket chat endpoint
│   ├── history.py              # State history & time travel API
│   ├── skills.py               # Skills management API
│   └── tools.py                # MCP tools API
│
├── utils/                      # Utilities
│   ├── __init__.py
│   ├── embeddings.py           # Embedding utilities
│   └── helpers.py              # Common helper functions
│
├── static/                     # Frontend assets
│   ├── index.html
│   ├── style.css
│   └── script.js
│
└── tests/                      # Test files
    ├── test_memory.py
    ├── test_hitl.py
    └── test_skills.py
```

## Module Responsibilities

| Module | Day | Purpose |
|--------|-----|---------|
| `core/memory` | 1 | MongoDB-based short-term and long-term memory |
| `core/hitl` | 2 | Human approval, interrupts, time travel |
| `core/sandbox` | 3 | Safe Docker-based code execution |
| `core/intelligence` | 4 | Reflection and self-improvement |
| `core/skills` | 5 | Skill recording and library |
| `core/synthesis` | 6 | Emergent skill creation |
| `core/agents` | 7 | Multi-agent orchestration |
| `core/proactive` | 8 | Proactive intelligence |
| `graph/` | 1-2 | LangGraph workflow definitions |
| `api/` | 1-10 | REST/WebSocket endpoints |
