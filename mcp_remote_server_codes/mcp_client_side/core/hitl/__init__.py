"""
Human-in-the-Loop Module
========================
Provides human oversight capabilities for the agentic bot.

Components:
- interrupt: Interrupt handling for human approval
- time_travel: Navigate conversation history, rewind, branch
- approval_gates: Configurable rules for when approval is needed
"""

from .interrupt import (
    InterruptType,
    InterruptStatus,
    InterruptRequest,
    InterruptManager,
    get_interrupt_manager,
)
from .time_travel import (
    StateSnapshot,
    TimeTravelResult,
    TimeTravelManager,
    get_time_travel_manager,
)
from .approval_gates import (
    RiskLevel,
    ApprovalRule,
    ApprovalCheck,
    ApprovalGateManager,
    get_approval_gates,
)

__all__ = [
    # Interrupt
    "InterruptType",
    "InterruptStatus",
    "InterruptRequest",
    "InterruptManager",
    "get_interrupt_manager",
    # Time Travel
    "StateSnapshot",
    "TimeTravelResult",
    "TimeTravelManager",
    "get_time_travel_manager",
    # Approval Gates
    "RiskLevel",
    "ApprovalRule",
    "ApprovalCheck",
    "ApprovalGateManager",
    "get_approval_gates",
]
