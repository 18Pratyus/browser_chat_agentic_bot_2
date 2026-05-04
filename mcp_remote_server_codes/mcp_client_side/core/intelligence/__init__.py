"""
Intelligence Module
===================
Self-improvement and learning capabilities for the agent.

Components:
- reflection: Self-critique after actions
- error_analyzer: Categorize and learn from errors
- prompt_optimizer: Improve prompts based on outcomes
- improvement_store: MongoDB storage for lessons
- skill_store: MongoDB storage for learned skills (Day 5)

Usage:
    from core.intelligence import get_reflection_system, get_improvement_store, get_skill_store

    store = await get_improvement_store()
    skill_store = await get_skill_store()
    reflection = await get_reflection_system(llm, store)

    # After an error
    result = await reflection.reflect_on_error(action, error, context)
    print(result.lesson_learned)

    # Store a skill
    skill_id = await skill_store.store_skill(...)
"""

from .improvement_store import (
    ImprovementStore,
    Lesson,
    LessonType,
    get_improvement_store,
)
from .reflection import (
    ReflectionSystem,
    ReflectionResult,
    ReflectionTrigger,
    get_reflection_system,
)
from .error_analyzer import (
    ErrorAnalyzer,
    ErrorCategory,
    ErrorRecord,
    ErrorPattern,
    get_error_analyzer,
)
from .prompt_optimizer import (
    PromptOptimizer,
    PromptIssue,
    PromptVersion,
    PromptOptimization,
    get_prompt_optimizer,
)
from .skill_store import (
    SkillStore,
    Skill,
    SkillType,
    SkillWorkflowStep,
    get_skill_store,
)
from .reasoning import (
    ReasoningResult,
    parse_thinking_response,
    format_thinking_for_display,
    format_thinking_for_storage,
    enhance_prompt_with_reasoning,
    get_reasoning_system_message,
    extract_skill_reasoning,
    REASONING_SYSTEM_PROMPT,
)

__all__ = [
    # Improvement Store
    "ImprovementStore",
    "Lesson",
    "LessonType",
    "get_improvement_store",
    # Reflection
    "ReflectionSystem",
    "ReflectionResult",
    "ReflectionTrigger",
    "get_reflection_system",
    # Error Analyzer
    "ErrorAnalyzer",
    "ErrorCategory",
    "ErrorRecord",
    "ErrorPattern",
    "get_error_analyzer",
    # Prompt Optimizer
    "PromptOptimizer",
    "PromptIssue",
    "PromptVersion",
    "PromptOptimization",
    "get_prompt_optimizer",
    # Skill Store (Day 5)
    "SkillStore",
    "Skill",
    "SkillType",
    "SkillWorkflowStep",
    "get_skill_store",
    # Reasoning (Day 5.5 - Chain of Thought)
    "ReasoningResult",
    "parse_thinking_response",
    "format_thinking_for_display",
    "format_thinking_for_storage",
    "enhance_prompt_with_reasoning",
    "get_reasoning_system_message",
    "extract_skill_reasoning",
    "REASONING_SYSTEM_PROMPT",
]
