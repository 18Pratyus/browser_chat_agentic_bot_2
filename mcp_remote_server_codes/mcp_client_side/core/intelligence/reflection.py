"""
Reflection System
=================
Self-critique and learning from actions.

The agent reflects on its actions to:
1. Identify what went wrong
2. Generate lessons learned
3. Improve future behavior
"""

from typing import Any, Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from langchain_core.messages import HumanMessage, AIMessage


class ReflectionTrigger(str, Enum):
    """When to trigger reflection."""
    ON_ERROR = "on_error"              # After an error
    ON_USER_FEEDBACK = "on_feedback"   # After negative feedback
    ON_RETRY = "on_retry"              # After needing to retry
    ON_SUCCESS = "on_success"          # After success (optional)
    PERIODIC = "periodic"              # Every N actions


@dataclass
class ReflectionResult:
    """Result of a reflection."""
    was_successful: bool
    lesson_learned: str
    improved_approach: str
    should_retry: bool
    confidence: float
    tags: List[str]


class ReflectionSystem:
    """
    Agent self-reflection and learning.

    Analyzes actions and outcomes to generate
    lessons that improve future behavior.
    """

    def __init__(self, llm: Any, improvement_store: Any):
        """
        Initialize reflection system.

        Args:
            llm: Language model for reflection analysis
            improvement_store: Storage for learned lessons
        """
        self.llm = llm
        self.store = improvement_store

    async def reflect_on_error(
        self,
        action: Dict[str, Any],
        error: str,
        context: str,
        user_message: str = None,
    ) -> ReflectionResult:
        """
        Reflect on an error and learn from it.

        Args:
            action: The action that failed (tool call, response, etc.)
            error: The error message
            context: What was the agent trying to do
            user_message: Original user request

        Returns:
            ReflectionResult with lesson and improved approach
        """
        reflection_prompt = f"""You are a self-improving AI agent. Analyze this failure and learn from it.

**Context:** {context}
**User Request:** {user_message or 'Not provided'}

**Action Taken:**
- Type: {action.get('type', 'unknown')}
- Name: {action.get('name', 'unknown')}
- Arguments: {action.get('args', {})}

**Error:** {error}

**Analyze and provide:**
1. ROOT_CAUSE: What specifically caused this failure?
2. LESSON: What should I remember to avoid this?
3. IMPROVED_APPROACH: How should I handle this differently next time?
4. SHOULD_RETRY: Can I retry with a different approach? (yes/no)
5. TAGS: Keywords for this lesson (comma-separated)

Format your response as:
ROOT_CAUSE: <analysis>
LESSON: <what to remember>
IMPROVED_APPROACH: <better way>
SHOULD_RETRY: <yes/no>
TAGS: <tag1, tag2, tag3>
"""

        response = await self.llm.ainvoke([HumanMessage(content=reflection_prompt)])
        content = response.content if hasattr(response, 'content') else str(response)

        # Parse response
        result = self._parse_reflection_response(content)

        # Store the lesson
        if self.store:
            await self.store.store_error_lesson(
                error_type=action.get('name', 'unknown'),
                context=context,
                original_action=action,
                error_message=error,
                lesson_learned=result.lesson_learned,
                improved_approach=result.improved_approach,
                tags=result.tags,
            )

        return result

    async def reflect_on_feedback(
        self,
        action: Dict[str, Any],
        result: Any,
        user_feedback: str,
        context: str,
    ) -> ReflectionResult:
        """
        Reflect on user feedback (positive or negative).

        Args:
            action: The action taken
            result: The result of the action
            user_feedback: What the user said
            context: What was being done

        Returns:
            ReflectionResult with lesson
        """
        is_negative = self._is_negative_feedback(user_feedback)

        reflection_prompt = f"""You are a self-improving AI agent. Learn from this user feedback.

**Context:** {context}

**Action Taken:**
- Type: {action.get('type', 'unknown')}
- Details: {action}

**Result:** {result}

**User Feedback:** {user_feedback}
**Feedback Type:** {"NEGATIVE - User was not satisfied" if is_negative else "POSITIVE - User was satisfied"}

**Analyze and provide:**
1. UNDERSTANDING: What did the user actually want?
2. GAP: Where was the mismatch between expectation and result?
3. LESSON: What should I remember for next time?
4. IMPROVED_APPROACH: How to better serve this type of request?
5. TAGS: Keywords for this lesson

Format your response as:
UNDERSTANDING: <what user wanted>
GAP: <where I fell short>
LESSON: <what to remember>
IMPROVED_APPROACH: <better way>
TAGS: <tag1, tag2>
"""

        response = await self.llm.ainvoke([HumanMessage(content=reflection_prompt)])
        content = response.content if hasattr(response, 'content') else str(response)

        result = self._parse_feedback_response(content, is_negative)

        # Store lesson if negative feedback
        if is_negative and self.store:
            await self.store.store_error_lesson(
                error_type="user_feedback_negative",
                context=context,
                original_action=action,
                error_message=f"User feedback: {user_feedback}",
                lesson_learned=result.lesson_learned,
                improved_approach=result.improved_approach,
                tags=result.tags,
            )

        return result

    async def reflect_on_success(
        self,
        actions: List[Dict[str, Any]],
        outcome: str,
        context: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Reflect on successful actions to identify patterns.

        Args:
            actions: List of actions that led to success
            outcome: The successful outcome
            context: What was being done

        Returns:
            Success pattern if identified
        """
        if len(actions) < 2:
            return None  # Not enough for a pattern

        reflection_prompt = f"""You are a self-improving AI agent. Identify successful patterns.

**Context:** {context}

**Actions Taken (in order):**
{self._format_actions(actions)}

**Outcome:** {outcome} (SUCCESS)

**Analyze and provide:**
1. PATTERN_TYPE: What type of task was this? (one word)
2. DESCRIPTION: Brief description of the successful approach
3. KEY_STEPS: The essential steps that led to success
4. REUSABLE: Is this pattern reusable for similar tasks? (yes/no)

Format your response as:
PATTERN_TYPE: <type>
DESCRIPTION: <brief description>
KEY_STEPS: <step1; step2; step3>
REUSABLE: <yes/no>
"""

        response = await self.llm.ainvoke([HumanMessage(content=reflection_prompt)])
        content = response.content if hasattr(response, 'content') else str(response)

        pattern = self._parse_success_response(content)

        if pattern and pattern.get("reusable") and self.store:
            await self.store.store_success_pattern(
                pattern_type=pattern.get("pattern_type", "general"),
                description=pattern.get("description", ""),
                actions=actions,
                context=context,
                outcome=outcome,
            )

        return pattern

    async def get_relevant_lessons(
        self,
        context: str,
        error_type: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Get lessons relevant to current context.

        Called BEFORE taking action to apply past learnings.
        """
        if not self.store:
            return []

        return await self.store.find_relevant_lessons(context, error_type)

    def _parse_reflection_response(self, content: str) -> ReflectionResult:
        """Parse LLM reflection response."""
        lines = content.strip().split('\n')

        lesson = ""
        improved = ""
        should_retry = False
        tags = []

        for line in lines:
            line = line.strip()
            if line.startswith("LESSON:"):
                lesson = line.replace("LESSON:", "").strip()
            elif line.startswith("IMPROVED_APPROACH:"):
                improved = line.replace("IMPROVED_APPROACH:", "").strip()
            elif line.startswith("SHOULD_RETRY:"):
                should_retry = "yes" in line.lower()
            elif line.startswith("TAGS:"):
                tags = [t.strip() for t in line.replace("TAGS:", "").split(",")]

        return ReflectionResult(
            was_successful=False,
            lesson_learned=lesson or "Analyze errors more carefully",
            improved_approach=improved or "Try alternative approach",
            should_retry=should_retry,
            confidence=0.5,
            tags=tags or ["error"],
        )

    def _parse_feedback_response(self, content: str, is_negative: bool) -> ReflectionResult:
        """Parse feedback reflection response."""
        lines = content.strip().split('\n')

        lesson = ""
        improved = ""
        tags = []

        for line in lines:
            line = line.strip()
            if line.startswith("LESSON:"):
                lesson = line.replace("LESSON:", "").strip()
            elif line.startswith("IMPROVED_APPROACH:"):
                improved = line.replace("IMPROVED_APPROACH:", "").strip()
            elif line.startswith("TAGS:"):
                tags = [t.strip() for t in line.replace("TAGS:", "").split(",")]

        return ReflectionResult(
            was_successful=not is_negative,
            lesson_learned=lesson or "Pay attention to user preferences",
            improved_approach=improved or "Ask clarifying questions",
            should_retry=is_negative,
            confidence=0.6 if is_negative else 0.8,
            tags=tags or ["feedback"],
        )

    def _parse_success_response(self, content: str) -> Dict[str, Any]:
        """Parse success pattern response."""
        lines = content.strip().split('\n')

        pattern = {}
        for line in lines:
            line = line.strip()
            if line.startswith("PATTERN_TYPE:"):
                pattern["pattern_type"] = line.replace("PATTERN_TYPE:", "").strip()
            elif line.startswith("DESCRIPTION:"):
                pattern["description"] = line.replace("DESCRIPTION:", "").strip()
            elif line.startswith("KEY_STEPS:"):
                pattern["key_steps"] = line.replace("KEY_STEPS:", "").strip()
            elif line.startswith("REUSABLE:"):
                pattern["reusable"] = "yes" in line.lower()

        return pattern

    def _is_negative_feedback(self, feedback: str) -> bool:
        """Detect if feedback is negative."""
        negative_indicators = [
            "wrong", "incorrect", "bad", "no", "not what",
            "didn't", "don't", "fail", "error", "mistake",
            "terrible", "awful", "useless", "stupid",
        ]
        feedback_lower = feedback.lower()
        return any(ind in feedback_lower for ind in negative_indicators)

    def _format_actions(self, actions: List[Dict[str, Any]]) -> str:
        """Format actions for prompt."""
        formatted = []
        for i, action in enumerate(actions, 1):
            formatted.append(f"{i}. {action.get('name', 'action')}: {action.get('args', {})}")
        return "\n".join(formatted)


# Singleton
_reflection_system: Optional[ReflectionSystem] = None


async def get_reflection_system(
    llm: Any,
    improvement_store: Any,
) -> ReflectionSystem:
    """Get or create reflection system."""
    global _reflection_system

    if _reflection_system is None:
        _reflection_system = ReflectionSystem(llm, improvement_store)
        print("[ReflectionSystem] Initialized")

    return _reflection_system
