import os
from dotenv import load_dotenv

load_dotenv()

# LLM Provider: "gemini" or "ollama"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")

# Gemini settings
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Ollama settings
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

# Model name (works for both providers)
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-1.5-flash")

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# MCP config path
MCP_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "mcp_config.json")
