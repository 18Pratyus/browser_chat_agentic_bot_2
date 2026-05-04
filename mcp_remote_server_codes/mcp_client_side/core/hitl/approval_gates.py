"""
Approval Gates for Critical Actions
====================================
Defines which actions require human approval before execution.

Features:
- Configurable approval rules
- Tool-based gates
- Action-based gates
- Risk level assessment
"""

from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import re


class RiskLevel(str, Enum):
    """Risk level of an action."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ApprovalRule:
    """A rule that determines if an action needs approval."""
    name: str
    description: str
    risk_level: RiskLevel
    tool_patterns: List[str] = field(default_factory=list)  # Regex patterns for tool names
    action_patterns: List[str] = field(default_factory=list)  # Regex patterns for action content
    always_approve: bool = False  # If True, always requires approval
    auto_approve: bool = False  # If True, auto-approve without asking


@dataclass
class ApprovalCheck:
    """Result of an approval check."""
    requires_approval: bool
    rule_name: Optional[str] = None
    risk_level: RiskLevel = RiskLevel.LOW
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class ApprovalGateManager:
    """
    Manages approval gates for the agent.

    Determines which actions require human approval based on:
    - Tool name patterns
    - Action content patterns
    - Risk level thresholds
    - Custom rules
    """

    def __init__(self):
        self.rules: List[ApprovalRule] = []
        self._setup_default_rules()

    def _setup_default_rules(self) -> None:
        """Set up default approval rules."""
        # Critical tools that always need approval
        self.add_rule(ApprovalRule(
            name="destructive_operations",
            description="Operations that can delete or modify important data",
            risk_level=RiskLevel.CRITICAL,
            tool_patterns=[
                r".*delete.*",
                r".*remove.*",
                r".*drop.*",
                r".*truncate.*",
            ],
            always_approve=True,
        ))

        # File system operations
        self.add_rule(ApprovalRule(
            name="file_write_operations",
            description="Operations that write to the file system",
            risk_level=RiskLevel.HIGH,
            tool_patterns=[
                r".*write.*file.*",
                r".*create.*file.*",
                r".*save.*",
            ],
        ))

        # Code execution
        self.add_rule(ApprovalRule(
            name="code_execution",
            description="Operations that execute code",
            risk_level=RiskLevel.HIGH,
            tool_patterns=[
                r".*execute.*",
                r".*run.*code.*",
                r".*eval.*",
                r".*exec.*",
            ],
        ))

        # External API calls
        self.add_rule(ApprovalRule(
            name="external_api_calls",
            description="Operations that make external API calls",
            risk_level=RiskLevel.MEDIUM,
            tool_patterns=[
                r".*api.*call.*",
                r".*http.*request.*",
                r".*webhook.*",
            ],
        ))

        # Database modifications
        self.add_rule(ApprovalRule(
            name="database_modifications",
            description="Operations that modify database data",
            risk_level=RiskLevel.MEDIUM,
            tool_patterns=[
                r".*insert.*",
                r".*update.*",
                r"add_expense",  # Your MCP tool
            ],
        ))

        # Safe operations that auto-approve
        self.add_rule(ApprovalRule(
            name="read_operations",
            description="Read-only operations",
            risk_level=RiskLevel.LOW,
            tool_patterns=[
                r".*list.*",
                r".*get.*",
                r".*read.*",
                r".*search.*",
                r".*query.*",
                r"summarize",  # Your MCP tool
                r"list_expenses",  # Your MCP tool
            ],
            auto_approve=True,
        ))

    def add_rule(self, rule: ApprovalRule) -> None:
        """Add an approval rule."""
        self.rules.append(rule)

    def remove_rule(self, rule_name: str) -> bool:
        """Remove a rule by name."""
        original_len = len(self.rules)
        self.rules = [r for r in self.rules if r.name != rule_name]
        return len(self.rules) < original_len

    def check_tool(
        self,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]] = None,
        threshold: RiskLevel = RiskLevel.MEDIUM
    ) -> ApprovalCheck:
        """
        Check if a tool call requires approval.

        Args:
            tool_name: Name of the tool
            tool_args: Tool arguments (optional, for content-based checks)
            threshold: Minimum risk level that requires approval

        Returns:
            ApprovalCheck result
        """
        risk_order = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }

        for rule in self.rules:
            # Check tool name patterns
            for pattern in rule.tool_patterns:
                if re.match(pattern, tool_name, re.IGNORECASE):
                    # Auto-approve if rule says so
                    if rule.auto_approve:
                        return ApprovalCheck(
                            requires_approval=False,
                            rule_name=rule.name,
                            risk_level=rule.risk_level,
                            message=f"Auto-approved by rule: {rule.name}",
                        )

                    # Always approve if rule says so
                    if rule.always_approve:
                        return ApprovalCheck(
                            requires_approval=True,
                            rule_name=rule.name,
                            risk_level=rule.risk_level,
                            message=f"Approval required: {rule.description}",
                            details={
                                "tool_name": tool_name,
                                "tool_args": tool_args,
                            }
                        )

                    # Check against threshold
                    if risk_order[rule.risk_level] >= risk_order[threshold]:
                        return ApprovalCheck(
                            requires_approval=True,
                            rule_name=rule.name,
                            risk_level=rule.risk_level,
                            message=f"Approval required ({rule.risk_level.value} risk): {rule.description}",
                            details={
                                "tool_name": tool_name,
                                "tool_args": tool_args,
                            }
                        )

        # No matching rule, default to no approval needed
        return ApprovalCheck(
            requires_approval=False,
            risk_level=RiskLevel.LOW,
            message="No approval rules matched",
        )

    def check_action(
        self,
        action_type: str,
        action_content: str,
        threshold: RiskLevel = RiskLevel.MEDIUM
    ) -> ApprovalCheck:
        """
        Check if an action requires approval based on content.

        Args:
            action_type: Type of action
            action_content: Content/description of the action
            threshold: Minimum risk level that requires approval

        Returns:
            ApprovalCheck result
        """
        risk_order = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }

        for rule in self.rules:
            for pattern in rule.action_patterns:
                if re.search(pattern, action_content, re.IGNORECASE):
                    if rule.auto_approve:
                        return ApprovalCheck(
                            requires_approval=False,
                            rule_name=rule.name,
                            risk_level=rule.risk_level,
                            message=f"Auto-approved by rule: {rule.name}",
                        )

                    if rule.always_approve or risk_order[rule.risk_level] >= risk_order[threshold]:
                        return ApprovalCheck(
                            requires_approval=True,
                            rule_name=rule.name,
                            risk_level=rule.risk_level,
                            message=f"Approval required: {rule.description}",
                            details={
                                "action_type": action_type,
                                "action_content": action_content[:200],  # Truncate for safety
                            }
                        )

        return ApprovalCheck(
            requires_approval=False,
            risk_level=RiskLevel.LOW,
            message="No approval rules matched",
        )

    def get_rules_summary(self) -> List[Dict[str, Any]]:
        """Get a summary of all rules."""
        return [
            {
                "name": rule.name,
                "description": rule.description,
                "risk_level": rule.risk_level.value,
                "tool_patterns": rule.tool_patterns,
                "always_approve": rule.always_approve,
                "auto_approve": rule.auto_approve,
            }
            for rule in self.rules
        ]

    def set_threshold(self, threshold: RiskLevel) -> None:
        """
        Set the default approval threshold.

        Actions at or above this risk level will require approval.
        """
        self._default_threshold = threshold


# Singleton
_approval_gates: Optional[ApprovalGateManager] = None


def get_approval_gates() -> ApprovalGateManager:
    """Get or create the approval gates manager."""
    global _approval_gates

    if _approval_gates is None:
        _approval_gates = ApprovalGateManager()
        print("[ApprovalGates] Initialized with default rules")

    return _approval_gates
