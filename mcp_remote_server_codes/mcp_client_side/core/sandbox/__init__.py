"""
Sandbox Execution Module
========================
Safe code execution in isolated Docker containers.

Features:
- Docker-based isolation
- Resource limits (CPU, memory, time)
- Network isolation
- File system bridge
- Multiple language support

Usage:
    from core.sandbox import get_code_runner, ExecutionTier

    runner = await get_code_runner()
    result = await runner.run("print('Hello!')", language="python")
    print(result.output)
"""

from .resource_limits import (
    ResourceLimits,
    ExecutionTier,
    get_limits,
    LIMIT_PROFILES,
    SECURITY_POLICIES,
)
from .docker_executor import (
    DockerExecutor,
    ExecutionResult,
    ExecutionStatus,
    get_docker_executor,
)
from .code_runner import (
    CodeRunner,
    CodeValidation,
    ValidationError,
    get_code_runner,
)
from .file_bridge import (
    FileBridge,
    FileEntry,
    WorkspaceConfig,
    get_file_bridge,
)

__all__ = [
    # Resource Limits
    "ResourceLimits",
    "ExecutionTier",
    "get_limits",
    "LIMIT_PROFILES",
    "SECURITY_POLICIES",
    # Docker Executor
    "DockerExecutor",
    "ExecutionResult",
    "ExecutionStatus",
    "get_docker_executor",
    # Code Runner
    "CodeRunner",
    "CodeValidation",
    "ValidationError",
    "get_code_runner",
    # File Bridge
    "FileBridge",
    "FileEntry",
    "WorkspaceConfig",
    "get_file_bridge",
]
