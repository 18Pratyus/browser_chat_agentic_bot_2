"""
Prompt Optimizer
================
Automatically improves prompts based on feedback and outcomes.

Features:
- Learn from user corrections
- Identify weak prompts
- Generate improved versions
- A/B test prompt variations
"""

from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PromptIssue(str, Enum):
    """Types of prompt issues."""
    TOO_VAGUE = "too_vague"              # Not specific enough
    MISSING_CONTEXT = "missing_context"   # Needed more context
    WRONG_FORMAT = "wrong_format"         # Output format was wrong
    MISUNDERSTOOD = "misunderstood"       # Misinterpreted request
    INCOMPLETE = "incomplete"             # Didn't cover all aspects
    TOO_LONG = "too_long"                 # Response was too verbose
    TOO_SHORT = "too_short"               # Response was too brief


@dataclass
class PromptVersion:
    """A version of a prompt."""
    id: str
    task_type: str
    prompt_template: str
    version: int
    created_at: datetime = field(default_factory=datetime.utcnow)
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0

    @property
    def success_rate(self) -> float:
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count


@dataclass
class PromptOptimization:
    """Result of prompt optimization."""
    original_prompt: str
    improved_prompt: str
    issues_fixed: List[PromptIssue]
    explanation: str
    confidence: float


class PromptOptimizer:
    """
    Optimizes prompts based on outcomes and feedback.

    Learns:
    - What phrasings work better
    - What context is needed
    - What format users prefer
    """

    def __init__(self, llm: Any, improvement_store: Any = None):
        self.llm = llm
        self.store = improvement_store

        # Track prompt versions in memory
        self._prompt_versions: Dict[str, List[PromptVersion]] = {}

    async def analyze_failure(
        self,
        prompt: str,
        response: str,
        expected: str,
        user_feedback: str = None,
    ) -> List[PromptIssue]:
        """
        Analyze why a prompt led to unsatisfactory result.

        Args:
            prompt: The prompt used
            response: The response generated
            expected: What was expected
            user_feedback: Optional user feedback

        Returns:
            List of identified issues
        """
        from langchain_core.messages import HumanMessage

        analysis_prompt = f"""Analyze why this prompt didn't produce the expected result.

**Prompt Used:**
{prompt}

**Response Generated:**
{response}

**Expected Result:**
{expected}

**User Feedback:** {user_feedback or 'Not provided'}

Identify the issues. For each issue found, output ONLY the issue code on a separate line:
- TOO_VAGUE: Prompt wasn't specific enough
- MISSING_CONTEXT: Needed more context
- WRONG_FORMAT: Output format was incorrect
- MISUNDERSTOOD: Request was misinterpreted
- INCOMPLETE: Didn't cover all aspects
- TOO_LONG: Response was too verbose
- TOO_SHORT: Response was too brief

Output format (one per line):
ISSUE: <issue_code>
"""

        result = await self.llm.ainvoke([HumanMessage(content=analysis_prompt)])
        content = result.content if hasattr(result, 'content') else str(result)

        # Parse issues
        issues = []
        for line in content.strip().split('\n'):
            line = line.strip()
            if line.startswith("ISSUE:"):
                issue_code = line.replace("ISSUE:", "").strip().upper()
                try:
                    issue = PromptIssue(issue_code.lower())
                    issues.append(issue)
                except ValueError:
                    pass

        return issues if issues else [PromptIssue.MISUNDERSTOOD]

    async def optimize_prompt(
        self,
        original_prompt: str,
        issues: List[PromptIssue],
        context: str = None,
        examples: List[Dict[str, str]] = None,
    ) -> PromptOptimization:
        """
        Generate an improved version of the prompt.

        Args:
            original_prompt: The prompt to improve
            issues: Identified issues to fix
            context: Additional context
            examples: Good/bad examples

        Returns:
            PromptOptimization with improved prompt
        """
        from langchain_core.messages import HumanMessage

        issues_desc = "\n".join([f"- {issue.value}: Fix this issue" for issue in issues])

        examples_text = ""
        if examples:
            examples_text = "\n**Examples to learn from:**\n"
            for ex in examples[:3]:
                examples_text += f"- Good: {ex.get('good', 'N/A')}\n"
                examples_text += f"- Bad: {ex.get('bad', 'N/A')}\n"

        optimization_prompt = f"""Improve this prompt to fix the identified issues.

**Original Prompt:**
{original_prompt}

**Issues to Fix:**
{issues_desc}

**Context:** {context or 'General use'}
{examples_text}

**Requirements for Improved Prompt:**
1. Be more specific and clear
2. Include necessary context
3. Specify expected output format
4. Handle edge cases

Provide your response in this format:
IMPROVED_PROMPT: <the improved prompt>
EXPLANATION: <what you changed and why>
CONFIDENCE: <0.0-1.0 how confident you are>
"""

        result = await self.llm.ainvoke([HumanMessage(content=optimization_prompt)])
        content = result.content if hasattr(result, 'content') else str(result)

        # Parse response
        improved = original_prompt
        explanation = "Minor improvements"
        confidence = 0.5

        for line in content.strip().split('\n'):
            line = line.strip()
            if line.startswith("IMPROVED_PROMPT:"):
                improved = line.replace("IMPROVED_PROMPT:", "").strip()
            elif line.startswith("EXPLANATION:"):
                explanation = line.replace("EXPLANATION:", "").strip()
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.replace("CONFIDENCE:", "").strip())
                except ValueError:
                    confidence = 0.5

        # Store the improvement
        if self.store:
            task_type = self._extract_task_type(original_prompt)
            await self.store.store_prompt_improvement(
                task_type=task_type,
                original_prompt=original_prompt,
                improved_prompt=improved,
                improvement_reason=explanation,
            )

        return PromptOptimization(
            original_prompt=original_prompt,
            improved_prompt=improved,
            issues_fixed=issues,
            explanation=explanation,
            confidence=confidence,
        )

    async def get_best_prompt(self, task_type: str) -> Optional[str]:
        """
        Get the best performing prompt for a task type.

        Args:
            task_type: Type of task

        Returns:
            Best prompt template or None
        """
        # Check store for improvements
        if self.store:
            improvement = await self.store.get_improved_prompt(task_type)
            if improvement:
                return improvement.get("improved_prompt")

        # Check in-memory versions
        versions = self._prompt_versions.get(task_type, [])
        if versions:
            # Get version with best success rate
            best = max(versions, key=lambda v: v.success_rate)
            if best.success_rate > 0.5:
                return best.prompt_template

        return None

    def record_prompt_outcome(
        self,
        task_type: str,
        prompt: str,
        was_successful: bool,
    ) -> None:
        """Record the outcome of using a prompt."""
        if task_type not in self._prompt_versions:
            self._prompt_versions[task_type] = []

        # Find or create version
        version = None
        for v in self._prompt_versions[task_type]:
            if v.prompt_template == prompt:
                version = v
                break

        if version is None:
            import uuid
            version = PromptVersion(
                id=f"pv_{uuid.uuid4().hex[:8]}",
                task_type=task_type,
                prompt_template=prompt,
                version=len(self._prompt_versions[task_type]) + 1,
            )
            self._prompt_versions[task_type].append(version)

        # Update stats
        version.usage_count += 1
        if was_successful:
            version.success_count += 1
        else:
            version.failure_count += 1

    def _extract_task_type(self, prompt: str) -> str:
        """Extract task type from prompt."""
        # Simple heuristic - first few words
        words = prompt.lower().split()[:5]
        keywords = ["analyze", "generate", "create", "find", "search", "summarize", "explain"]

        for word in words:
            if word in keywords:
                return word

        return "general"

    def get_optimization_stats(self) -> Dict[str, Any]:
        """Get statistics about prompt optimization."""
        total_versions = sum(len(v) for v in self._prompt_versions.values())
        task_types = list(self._prompt_versions.keys())

        best_performers = {}
        for task, versions in self._prompt_versions.items():
            if versions:
                best = max(versions, key=lambda v: v.success_rate)
                best_performers[task] = {
                    "version": best.version,
                    "success_rate": best.success_rate,
                    "usage_count": best.usage_count,
                }

        return {
            "total_versions": total_versions,
            "task_types": task_types,
            "best_performers": best_performers,
        }


# Singleton
_prompt_optimizer: Optional[PromptOptimizer] = None


async def get_prompt_optimizer(
    llm: Any,
    improvement_store: Any = None,
) -> PromptOptimizer:
    """Get or create prompt optimizer instance."""
    global _prompt_optimizer

    if _prompt_optimizer is None:
        _prompt_optimizer = PromptOptimizer(llm, improvement_store)
        print("[PromptOptimizer] Initialized")

    return _prompt_optimizer
