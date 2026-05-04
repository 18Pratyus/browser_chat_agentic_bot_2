"""
Error Analyzer
==============
Analyzes errors to identify patterns and root causes.

Features:
- Categorize errors
- Identify recurring patterns
- Suggest preventive measures
- Track error frequency
"""

from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict


class ErrorCategory(str, Enum):
    """Categories of errors."""
    TOOL_FAILURE = "tool_failure"           # Tool execution failed
    INVALID_ARGS = "invalid_args"           # Wrong arguments to tool
    TIMEOUT = "timeout"                     # Operation timed out
    PERMISSION = "permission"               # Permission denied
    NOT_FOUND = "not_found"                 # Resource not found
    PARSE_ERROR = "parse_error"             # Failed to parse response
    API_ERROR = "api_error"                 # External API error
    USER_REJECTION = "user_rejection"       # User rejected action
    CONTEXT_MISSING = "context_missing"     # Missing required context
    UNKNOWN = "unknown"                     # Unknown error


@dataclass
class ErrorRecord:
    """Record of an error occurrence."""
    id: str
    category: ErrorCategory
    error_message: str
    context: str
    action: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolution: Optional[str] = None


@dataclass
class ErrorPattern:
    """A recurring error pattern."""
    category: ErrorCategory
    frequency: int
    last_occurrence: datetime
    common_contexts: List[str]
    suggested_fix: str


class ErrorAnalyzer:
    """
    Analyzes errors to find patterns and suggest fixes.

    Tracks:
    - Error frequency by category
    - Recurring patterns
    - Context-specific errors
    - Resolution effectiveness
    """

    def __init__(self, improvement_store: Any = None):
        self.store = improvement_store

        # In-memory error tracking (for session)
        self._error_history: List[ErrorRecord] = []
        self._error_counts: Dict[ErrorCategory, int] = defaultdict(int)
        self._context_errors: Dict[str, List[ErrorRecord]] = defaultdict(list)

    def categorize_error(self, error_message: str) -> ErrorCategory:
        """
        Categorize an error based on its message.

        Args:
            error_message: The error message

        Returns:
            ErrorCategory
        """
        error_lower = error_message.lower()

        # Tool failures
        if any(x in error_lower for x in ["tool not found", "tool failed", "execution error"]):
            return ErrorCategory.TOOL_FAILURE

        # Invalid arguments
        if any(x in error_lower for x in ["invalid", "argument", "parameter", "type error", "missing required"]):
            return ErrorCategory.INVALID_ARGS

        # Timeouts
        if any(x in error_lower for x in ["timeout", "timed out", "deadline exceeded"]):
            return ErrorCategory.TIMEOUT

        # Permission
        if any(x in error_lower for x in ["permission", "denied", "unauthorized", "forbidden"]):
            return ErrorCategory.PERMISSION

        # Not found
        if any(x in error_lower for x in ["not found", "404", "does not exist", "no such"]):
            return ErrorCategory.NOT_FOUND

        # Parse errors
        if any(x in error_lower for x in ["parse", "json", "syntax", "decode", "format"]):
            return ErrorCategory.PARSE_ERROR

        # API errors
        if any(x in error_lower for x in ["api", "request failed", "connection", "network"]):
            return ErrorCategory.API_ERROR

        # User rejection
        if any(x in error_lower for x in ["rejected", "cancelled", "user declined"]):
            return ErrorCategory.USER_REJECTION

        # Context missing
        if any(x in error_lower for x in ["context", "missing", "required", "undefined"]):
            return ErrorCategory.CONTEXT_MISSING

        return ErrorCategory.UNKNOWN

    async def record_error(
        self,
        error_message: str,
        context: str,
        action: Dict[str, Any],
    ) -> ErrorRecord:
        """
        Record an error for analysis.

        Args:
            error_message: The error message
            context: What was being attempted
            action: The action that caused the error

        Returns:
            ErrorRecord
        """
        import uuid

        category = self.categorize_error(error_message)

        record = ErrorRecord(
            id=f"err_{uuid.uuid4().hex[:8]}",
            category=category,
            error_message=error_message,
            context=context,
            action=action,
        )

        # Track in memory
        self._error_history.append(record)
        self._error_counts[category] += 1
        self._context_errors[context[:50]].append(record)

        # Keep history bounded
        if len(self._error_history) > 1000:
            self._error_history = self._error_history[-500:]

        return record

    def get_error_patterns(self, min_frequency: int = 2) -> List[ErrorPattern]:
        """
        Identify recurring error patterns.

        Args:
            min_frequency: Minimum occurrences to be a pattern

        Returns:
            List of ErrorPattern
        """
        patterns = []

        for category, count in self._error_counts.items():
            if count >= min_frequency:
                # Find common contexts for this category
                contexts = []
                last_time = None

                for record in self._error_history:
                    if record.category == category:
                        contexts.append(record.context[:50])
                        if last_time is None or record.timestamp > last_time:
                            last_time = record.timestamp

                # Get unique contexts
                unique_contexts = list(set(contexts))[:5]

                # Generate suggested fix
                suggested_fix = self._suggest_fix(category)

                patterns.append(ErrorPattern(
                    category=category,
                    frequency=count,
                    last_occurrence=last_time or datetime.utcnow(),
                    common_contexts=unique_contexts,
                    suggested_fix=suggested_fix,
                ))

        # Sort by frequency
        patterns.sort(key=lambda p: p.frequency, reverse=True)
        return patterns

    def _suggest_fix(self, category: ErrorCategory) -> str:
        """Generate fix suggestion for error category."""
        suggestions = {
            ErrorCategory.TOOL_FAILURE: "Verify tool availability and check input format",
            ErrorCategory.INVALID_ARGS: "Validate arguments before tool call, check types",
            ErrorCategory.TIMEOUT: "Reduce operation scope or increase timeout",
            ErrorCategory.PERMISSION: "Check permissions or request user approval",
            ErrorCategory.NOT_FOUND: "Verify resource exists before accessing",
            ErrorCategory.PARSE_ERROR: "Validate JSON/response format before parsing",
            ErrorCategory.API_ERROR: "Add retry logic with exponential backoff",
            ErrorCategory.USER_REJECTION: "Provide clearer explanation before requesting",
            ErrorCategory.CONTEXT_MISSING: "Gather required context before action",
            ErrorCategory.UNKNOWN: "Log detailed error info for investigation",
        }
        return suggestions.get(category, "Investigate error details")

    async def get_prevention_advice(
        self,
        planned_action: Dict[str, Any],
        context: str,
    ) -> Optional[str]:
        """
        Get advice to prevent errors before taking action.

        Checks if similar actions have failed before.

        Args:
            planned_action: The action about to be taken
            context: Current context

        Returns:
            Prevention advice if relevant errors found
        """
        action_name = planned_action.get("name", "")

        # Check if this action type has failed before
        relevant_errors = [
            r for r in self._error_history
            if r.action.get("name") == action_name and not r.resolved
        ]

        if not relevant_errors:
            return None

        # Get most recent error
        recent = max(relevant_errors, key=lambda r: r.timestamp)

        # Check if it's recent (within last hour)
        if datetime.utcnow() - recent.timestamp > timedelta(hours=1):
            return None

        return f"Warning: '{action_name}' failed recently with: {recent.error_message}. Consider: {self._suggest_fix(recent.category)}"

    def get_session_stats(self) -> Dict[str, Any]:
        """Get error statistics for current session."""
        total = len(self._error_history)

        category_breakdown = {
            cat.value: count
            for cat, count in self._error_counts.items()
        }

        return {
            "total_errors": total,
            "by_category": category_breakdown,
            "patterns_found": len(self.get_error_patterns()),
            "most_common": max(self._error_counts.items(), key=lambda x: x[1])[0].value if self._error_counts else None,
        }

    def clear_session(self) -> None:
        """Clear session error tracking."""
        self._error_history.clear()
        self._error_counts.clear()
        self._context_errors.clear()


# Singleton
_error_analyzer: Optional[ErrorAnalyzer] = None


def get_error_analyzer(improvement_store: Any = None) -> ErrorAnalyzer:
    """Get or create error analyzer instance."""
    global _error_analyzer

    if _error_analyzer is None:
        _error_analyzer = ErrorAnalyzer(improvement_store)
        print("[ErrorAnalyzer] Initialized")

    return _error_analyzer
