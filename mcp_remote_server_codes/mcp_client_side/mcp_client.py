import json
from langchain_mcp_adapters.client import MultiServerMCPClient
from config import MCP_CONFIG_PATH


def load_mcp_config() -> dict:
    """Load MCP server configuration from JSON file."""
    try:
        with open(MCP_CONFIG_PATH, "r") as f:
            config = json.load(f)
            return config.get("servers", {})
    except FileNotFoundError:
        print(f"Warning: {MCP_CONFIG_PATH} not found. Using empty config.")
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing MCP config: {e}")
        return {}


def get_mcp_client():
    """Create and return MCP client with configured servers."""
    servers = load_mcp_config()
    if not servers:
        return None
    return MultiServerMCPClient(servers)


async def get_mcp_tools(client: MultiServerMCPClient) -> list:
    """Get all available tools from connected MCP servers."""
    if client is None:
        return []
    try:
        return client.get_tools()
    except Exception as e:
        print(f"Error getting MCP tools: {e}")
        return []
