"""
===============================================================================
REASONING MODULE - Chain-of-Thought Capture
===============================================================================

Captures LLM's internal reasoning/thinking process like a child thinking
step-by-step before answering.

Features:
- Force chain-of-thought prompting
- Parse thinking and answer separately
- Store reasoning for skill learning
- Compatible with any LLM (Ollama, OpenAI, Claude)

Example Output:
<thinking>
1. User wants to list all expenses
2. I need to use the list_expenses tool
3. No date filter specified, so fetch all
4. Format as a readable table
</thinking>
<answer>
Here are your expenses...
</answer>
"""

import re
from typing import Tuple, Optional, List
from dataclasses import dataclass


# ==============================================================================
# REASONING SYSTEM PROMPT
# ==============================================================================

REASONING_SYSTEM_PROMPT = """You are a helpful AI assistant with chain-of-thought reasoning.

CRITICAL REQUIREMENT - You MUST structure EVERY response like this:

<thinking>
[Your step-by-step reasoning here - analyze the request, consider options, plan your approach]
</thinking>

<answer>
[Your final response to the user]
</answer>

MANDATORY RULES:
1. EVERY response MUST start with <thinking> tags - NO EXCEPTIONS
2. Even for simple greetings like "hi", show your thinking process
3. Your thinking should be genuine reasoning, not generic phrases
4. For tool usage: explain WHY you chose each tool in your thinking
5. For questions: show how you arrive at the answer
6. The <answer> section contains ONLY what the user sees

Example for "hi":
<thinking>
The user is greeting me. I should respond warmly and offer help. Since this is a casual greeting, I'll keep my response friendly and open-ended to invite further conversation.
</thinking>

<answer>
Hello! How can I help you today?
</answer>

NEVER skip the <thinking> section. Your response will be REJECTED if it doesn't contain <thinking> tags.
"""


# ==============================================================================
# DATA STRUCTURES
# ==============================================================================

@dataclass
class ReasoningResult:
    """Parsed result containing thinking and answer."""
    thinking: str               # The step-by-step reasoning
    answer: str                 # The final answer for user
    thinking_steps: List[str]   # Parsed individual steps
    raw_response: str           # Original full response
    has_thinking: bool          # Whether thinking was found


# ==============================================================================
# PARSING FUNCTIONS
# ==============================================================================

def parse_thinking_response(response: str) -> ReasoningResult:
    """
    Parse LLM response to extract thinking and answer.

    Handles multiple formats:
    - <thinking>...</thinking><answer>...</answer>
    - Just answer (no thinking tags)
    - Malformed responses

    Args:
        response: Raw LLM response string

    Returns:
        ReasoningResult with parsed components
    """
    if not response:
        return ReasoningResult(
            thinking="",
            answer="",
            thinking_steps=[],
            raw_response="",
            has_thinking=False
        )

    # Pattern to extract thinking block
    thinking_pattern = r'<thinking>(.*?)</thinking>'
    thinking_match = re.search(thinking_pattern, response, re.DOTALL | re.IGNORECASE)

    # Pattern to extract answer block
    answer_pattern = r'<answer>(.*?)</answer>'
    answer_match = re.search(answer_pattern, response, re.DOTALL | re.IGNORECASE)

    thinking = ""
    answer = ""
    has_thinking = False

    if thinking_match:
        thinking = thinking_match.group(1).strip()
        has_thinking = True

    if answer_match:
        answer = answer_match.group(1).strip()
    else:
        # No <answer> tags - try to extract content after </thinking>
        if thinking_match:
            after_thinking = response[thinking_match.end():].strip()
            # Remove any stray tags
            answer = re.sub(r'</?answer>', '', after_thinking).strip()
        else:
            # No tags at all - treat entire response as answer
            answer = response.strip()

    # Parse individual thinking steps
    thinking_steps = _parse_thinking_steps(thinking)

    return ReasoningResult(
        thinking=thinking,
        answer=answer,
        thinking_steps=thinking_steps,
        raw_response=response,
        has_thinking=has_thinking
    )


def _parse_thinking_steps(thinking: str) -> List[str]:
    """
    Parse thinking text into individual steps.

    Handles formats:
    - Numbered: 1. Step one  2. Step two
    - Bullet: - Step one  - Step two
    - Newline separated
    """
    if not thinking:
        return []

    steps = []

    # Try numbered format first (1. 2. 3.)
    numbered_pattern = r'(?:^|\n)\s*(\d+)[.):]\s*(.+?)(?=(?:\n\s*\d+[.):])|\Z)'
    numbered_matches = re.findall(numbered_pattern, thinking, re.DOTALL)

    if numbered_matches:
        for num, step in numbered_matches:
            clean_step = step.strip()
            if clean_step:
                steps.append(f"{num}. {clean_step}")
        return steps

    # Try bullet format (- or *)
    bullet_pattern = r'(?:^|\n)\s*[-*]\s*(.+?)(?=(?:\n\s*[-*])|\Z)'
    bullet_matches = re.findall(bullet_pattern, thinking, re.DOTALL)

    if bullet_matches:
        for i, step in enumerate(bullet_matches, 1):
            clean_step = step.strip()
            if clean_step:
                steps.append(f"{i}. {clean_step}")
        return steps

    # Fallback: split by newlines
    lines = thinking.split('\n')
    for i, line in enumerate(lines, 1):
        clean_line = line.strip()
        if clean_line and len(clean_line) > 5:  # Skip very short lines
            steps.append(f"{i}. {clean_line}")

    return steps


def format_thinking_for_display(thinking_steps: List[str]) -> str:
    """
    Format thinking steps for UI display.

    Returns a clean, readable format.
    """
    if not thinking_steps:
        return "No detailed reasoning captured."

    return "\n".join(thinking_steps)


def format_thinking_for_storage(result: ReasoningResult) -> dict:
    """
    Format reasoning result for database storage.

    Returns dict compatible with skill_store schema.
    """
    return {
        "thinking_raw": result.thinking,
        "thinking_steps": result.thinking_steps,
        "has_thinking": result.has_thinking,
        "step_count": len(result.thinking_steps),
    }


# ==============================================================================
# PROMPT ENHANCEMENT
# ==============================================================================

def enhance_prompt_with_reasoning(original_prompt: str) -> str:
    """
    Enhance a prompt to force chain-of-thought reasoning.

    Args:
        original_prompt: The original user/system prompt

    Returns:
        Enhanced prompt with reasoning instructions
    """
    return f"""{REASONING_SYSTEM_PROMPT}

User's request: {original_prompt}

Remember: ALWAYS show your thinking in <thinking> tags first!"""


def get_reasoning_system_message() -> str:
    """Get the system message for reasoning mode."""
    return REASONING_SYSTEM_PROMPT


# ==============================================================================
# TOOL CALL REASONING
# ==============================================================================

def create_tool_reasoning_prompt(tool_name: str, tool_args: dict, user_query: str) -> str:
    """
    Create a prompt asking LLM to explain its tool choice reasoning.

    Used when capturing detailed workflow for skill storage.
    """
    return f"""Explain your reasoning for using this tool:

User Query: {user_query}
Tool Chosen: {tool_name}
Tool Arguments: {tool_args}

<thinking>
Explain step-by-step:
1. Why did you choose this specific tool?
2. Why these specific arguments?
3. What result do you expect?
4. How will this help the user?
</thinking>"""


# ==============================================================================
# SKILL REASONING EXTRACTION
# ==============================================================================

def extract_skill_reasoning(
    user_query: str,
    tool_calls: List[dict],
    final_answer: str,
    thinking: str = ""
) -> dict:
    """
    Extract complete reasoning for skill storage.

    Combines user query, tool usage, thinking, and answer
    into a structured format for learned_skills collection.

    Args:
        user_query: Original user question
        tool_calls: List of tools used with args
        final_answer: Final LLM response
        thinking: Captured thinking (if any)

    Returns:
        Dict with reasoning_steps for skill storage
    """
    reasoning = {
        "user_intent": user_query[:200],
        "thinking_process": thinking,
        "thinking_steps": _parse_thinking_steps(thinking),
        "tool_decisions": [],
        "final_approach": "",
    }

    # Document each tool decision
    for i, tc in enumerate(tool_calls, 1):
        tool_decision = {
            "step": i,
            "tool": tc.get("name", "unknown"),
            "args": tc.get("args", {}),
            "reason": f"Step {i}: Use {tc.get('name')} to handle user request",
        }
        reasoning["tool_decisions"].append(tool_decision)

    # Summarize approach
    if tool_calls:
        tool_names = [tc.get("name", "unknown") for tc in tool_calls]
        reasoning["final_approach"] = f"Used {', '.join(tool_names)} to fulfill user request"
    else:
        reasoning["final_approach"] = "Direct response without tool usage"

    return reasoning
