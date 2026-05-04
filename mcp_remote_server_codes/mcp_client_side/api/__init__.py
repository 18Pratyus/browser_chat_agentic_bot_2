"""
API Module
==========
REST and WebSocket API endpoints.

Components:
- history: Time travel API endpoints
- (future) skills: Skills management API
- (future) interrupts: Interrupt management API
"""

from .history import router as history_router

__all__ = [
    "history_router",
]
