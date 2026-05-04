from typing import Literal
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage


def should_continue(state: MessagesState) -> Literal["tools", "end"]:
    """Decide whether to call tools or end the conversation."""
    last_message = state["messages"][-1]

    # If the LLM made tool calls, route to tools node
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    # Otherwise, end the conversation
    return "end"


def create_agent(llm_with_tools, tools: list):
    """
    Create a LangGraph agent with the given LLM and tools.

    Graph structure:
        START → agent → (tools → agent)* → END

    Args:
        llm_with_tools: LLM with tools bound
        tools: List of tools for ToolNode

    Returns:
        Compiled LangGraph agent
    """

    async def call_llm(state: MessagesState):
        """Agent node: call the LLM with current messages."""
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    # Create the graph
    graph = StateGraph(MessagesState)

    # Add nodes
    graph.add_node("agent", call_llm)
    graph.add_node("tools", ToolNode(tools))

    # Add edges
    graph.add_edge(START, "agent")

    # Conditional edge: tools or end?
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END,
        },
    )

    # After tools, go back to agent
    graph.add_edge("tools", "agent")

    # Compile and return
    return graph.compile()
