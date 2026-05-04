from config import GOOGLE_API_KEY, MODEL_NAME, LLM_PROVIDER, OLLAMA_HOST, OLLAMA_API_KEY


def get_llm():
    """Create and return LLM instance based on provider."""

    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=MODEL_NAME,
            base_url=OLLAMA_HOST,
            headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else {},
            streaming=True,
            temperature=0.7,
        )
    else:
        # Default: Gemini
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not set in .env file")

        return ChatGoogleGenerativeAI(
            model=MODEL_NAME,
            google_api_key=GOOGLE_API_KEY,
            streaming=True,
            temperature=0.7,
        )


def get_llm_with_tools(tools: list):
    """Create LLM with tools bound for agent use."""
    llm = get_llm()
    if tools:
        return llm.bind_tools(tools)
    return llm
