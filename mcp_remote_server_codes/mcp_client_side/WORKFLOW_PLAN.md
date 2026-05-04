# Custom Claude-Like MCP Client — Workflow Plan

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | HTML/CSS/JS (Vanilla) | Claude-like chat UI |
| Backend | FastAPI + WebSocket | Python server on localhost |
| LLM Orchestration | LangChain + LangGraph | Agent loop, tool calling, multi-step reasoning |
| MCP Connection | langchain-mcp-adapters | Connect to FastMCP servers (stdio/HTTP) |
| LLM | Gemini API (via langchain-google-genai) | Intelligence layer |
| File Upload | FastAPI UploadFile | Handle user file uploads |

---

## LangChain — What & Why

LangChain is a framework for building LLM-powered applications. We use specific parts:

### Features We Use

| Feature | What It Does | Why We Need It | Where Used |
|---------|-------------|----------------|------------|
| **ChatGoogleGenerativeAI** | Wrapper for Gemini API | Provides unified interface to call Gemini with messages | `app.py` — LLM initialization |
| **Messages (HumanMessage, AIMessage, ToolMessage)** | Standardized message format | Maintains conversation history in proper format for LLM | Agent state, conversation storage |
| **bind_tools()** | Attaches tools to LLM | Lets Gemini know what MCP tools are available to call | Tool binding before agent runs |
| **ToolNode** | Executes tool calls | When LLM decides to call a tool, this actually runs it | LangGraph node for tool execution |
| **Streaming (astream_events)** | Token-by-token output | Real-time typing effect like Claude — no waiting for full response | WebSocket response streaming |

### Code Example — LangChain Setup
```python
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# Initialize Gemini
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key="your-api-key",
    streaming=True  # Enable token streaming
)

# Bind MCP tools to LLM
llm_with_tools = llm.bind_tools(mcp_tools)
```

---

## LangGraph — What & Why

LangGraph builds **stateful, multi-step agents** using a graph structure. This is the brain of our Claude-like assistant.

### Why LangGraph (not just LangChain)?

| Problem | LangChain Alone | LangGraph Solution |
|---------|-----------------|-------------------|
| Multi-step tool calls | Manual loop needed | Built-in agent loop |
| State management | You manage it | Automatic state tracking |
| Conditional logic | If-else chains | Graph edges with conditions |
| Streaming mid-execution | Complex | Native support |

### Features We Use

| Feature | What It Does | Why We Need It | Where Used |
|---------|-------------|----------------|------------|
| **StateGraph** | Defines agent as a graph | Structures the agent flow (think → act → observe → repeat) | Core agent definition |
| **MessagesState** | Built-in state for messages | Automatically tracks conversation history | Agent state type |
| **add_node()** | Adds processing steps | Creates "agent" node (LLM thinking) and "tools" node (tool execution) | Graph construction |
| **add_edge()** | Connects nodes | Defines flow: START → agent → tools → agent → END | Graph flow |
| **add_conditional_edges()** | Dynamic routing | If LLM wants tool → go to tools node; else → END | Decision logic |
| **compile()** | Builds runnable agent | Converts graph definition into executable agent | Final agent creation |
| **astream()** | Async streaming | Streams agent events (tokens, tool calls, results) in real-time | WebSocket integration |

### Agent Graph Structure

```
┌─────────────────────────────────────────────────────────┐
│                    LangGraph Agent                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   START                                                 │
│     │                                                   │
│     ▼                                                   │
│  ┌──────────┐                                          │
│  │  AGENT   │  ← Gemini LLM thinks here                │
│  │  (LLM)   │    "Should I call a tool or respond?"    │
│  └────┬─────┘                                          │
│       │                                                 │
│       ▼                                                 │
│  ┌──────────────────┐                                  │
│  │ CONDITIONAL EDGE │                                  │
│  │  has_tool_calls? │                                  │
│  └────┬────────┬────┘                                  │
│       │        │                                        │
│    YES│        │NO                                      │
│       ▼        ▼                                        │
│  ┌────────┐  ┌─────┐                                   │
│  │ TOOLS  │  │ END │  → Final response to user         │
│  │ (MCP)  │  └─────┘                                   │
│  └────┬───┘                                            │
│       │                                                 │
│       └────────► Back to AGENT (loop continues)        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Code Example — LangGraph Agent
```python
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode

# Define the graph
graph = StateGraph(MessagesState)

# Add nodes
graph.add_node("agent", call_llm)      # LLM decides what to do
graph.add_node("tools", ToolNode(tools))  # Execute MCP tools

# Add edges
graph.add_edge(START, "agent")  # Start with agent thinking

# Conditional edge: tool call or end?
graph.add_conditional_edges(
    "agent",
    should_continue,  # Function that checks for tool_calls
    {
        "continue": "tools",  # Has tool calls → execute tools
        "end": END            # No tool calls → respond to user
    }
)

# After tools, go back to agent
graph.add_edge("tools", "agent")

# Compile the agent
agent = graph.compile()
```

---

## MCP Integration — langchain-mcp-adapters

This bridges LangChain/LangGraph with MCP protocol.

### Features We Use

| Feature | What It Does | Why We Need It |
|---------|-------------|----------------|
| **MultiServerMCPClient** | Connects to multiple MCP servers | We may have ExpenseTracker + FileSystem servers |
| **get_tools()** | Fetches available tools from MCP server | Dynamically discover what tools are available |
| **Tool execution** | Runs MCP tools via JSON-RPC | When agent calls `add_expense`, this sends it to MCP server |

### Code Example — MCP Connection
```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient(
    {
        "expense": {
            "transport": "http",
            "url": "http://localhost:8001/mcp"
        },
        "filesystem": {
            "transport": "stdio",
            "command": "python",
            "args": ["file_server.py"]
        }
    }
) as mcp_client:
    # Get all tools from all servers
    tools = mcp_client.get_tools()

    # Bind to LLM
    llm_with_tools = llm.bind_tools(tools)
```

---

## Complete Agent Flow — Step by Step

```
User: "Add expense for lunch Rs 500 today"
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 1. WebSocket receives message                           │
│    FastAPI endpoint: /ws                                │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Create HumanMessage, add to conversation history     │
│    messages = [HumanMessage(content="Add expense...")]  │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 3. LangGraph Agent starts (astream)                     │
│    agent.astream({"messages": messages})                │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 4. AGENT NODE — Gemini LLM thinks                       │
│    Input: conversation history                          │
│    Output: "I should call add_expense tool"             │
│    Returns: AIMessage with tool_calls                   │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 5. CONDITIONAL EDGE — has_tool_calls? YES               │
│    Route to: "tools" node                               │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 6. TOOLS NODE — Execute MCP tool                        │
│    Tool: add_expense                                    │
│    Args: {date: "2024-01-28", amount: 500, ...}        │
│    → JSON-RPC to FastMCP server                         │
│    → Returns: {status: "success", id: 42}               │
│    Output: ToolMessage with result                      │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 7. Back to AGENT NODE — Gemini sees tool result         │
│    Input: [..., ToolMessage(content="success")]         │
│    Output: "I've added your expense successfully!"      │
│    Returns: AIMessage (no tool_calls)                   │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 8. CONDITIONAL EDGE — has_tool_calls? NO                │
│    Route to: END                                        │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 9. Stream response tokens via WebSocket                 │
│    "I've" → "added" → "your" → "expense" → ...         │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│ 10. Browser JS renders tokens in chat bubble            │
│     Real-time typing effect!                            │
└─────────────────────────────────────────────────────────┘
```

---

## File Structure (Updated)

```
mcp_client_side/
├── app.py                  # FastAPI + WebSocket + LangGraph agent
├── agent.py                # LangGraph agent definition (graph)
├── mcp_client.py           # MCP connection manager
├── static/
│   ├── index.html          # Chat UI
│   ├── style.css           # Styling
│   └── script.js           # WebSocket client
├── mcp_config.json         # MCP server configs
├── uploads/                # Uploaded files
├── requirements.txt        # Dependencies
└── .env                    # GOOGLE_API_KEY
```

---

## Dependencies (Final)

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
websockets
python-dotenv==1.0.1
python-multipart==0.0.12
aiofiles==24.1.0

# LangChain
langchain>=0.3.0
langchain-core>=0.3.0
langchain-google-genai>=2.0.0

# LangGraph
langgraph>=0.2.0
langgraph-prebuilt>=0.0.1

# MCP
langchain-mcp-adapters>=0.1.0
mcp>=1.0.0
httpx>=0.27.0
```

---

## Summary: Why This Stack?

| Component | Alternative | Why We Chose This |
|-----------|-------------|-------------------|
| **LangGraph** | Raw LangChain chains | Built-in agent loop, state management, streaming |
| **Gemini** | OpenAI, Claude | Free tier, good tool calling, your choice |
| **langchain-mcp-adapters** | Manual JSON-RPC | Seamless MCP ↔ LangChain tool conversion |
| **WebSocket** | HTTP polling | Real-time streaming, no page refresh |
| **FastAPI** | Flask | Async native, WebSocket support, fast |

This architecture creates a **Claude Cowork-like agent** that:
1. Understands natural language (Gemini)
2. Decides when to use tools (LangGraph conditional edges)
3. Calls MCP tools (langchain-mcp-adapters)
4. Streams responses in real-time (WebSocket + astream)
5. Maintains conversation context (MessagesState)
