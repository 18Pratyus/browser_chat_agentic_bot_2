"""
Code Runner
===========
High-level interface for safe code execution.

Features:
- Code validation before execution
- Multiple language support
- Result formatting
- Fallback to subprocess if Docker unavailable
"""

import asyncio
import subprocess
import tempfile
import os
import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

from .docker_executor import (
    DockerExecutor,
    ExecutionResult,
    ExecutionStatus,
    get_docker_executor,
)
from .resource_limits import (
    ResourceLimits,
    ExecutionTier,
    get_limits,
    SECURITY_POLICIES,
)


class ValidationError(Exception):
    """Raised when code validation fails."""
    pass


@dataclass
class CodeValidation:
    """Result of code validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    sanitized_code: Optional[str] = None


class CodeRunner:
    """
    High-level code execution interface.

    Provides:
    - Code validation and sanitization
    - Docker execution (preferred)
    - Subprocess fallback (restricted)
    - Result formatting
    """

    def __init__(self):
        self._docker: Optional[DockerExecutor] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the code runner."""
        try:
            self._docker = await get_docker_executor()
            self._initialized = self._docker.is_available

            if not self._initialized:
                print("[CodeRunner] Docker unavailable, using restricted subprocess mode")

            return True
        except Exception as e:
            print(f"[CodeRunner] Initialization error: {e}")
            return False

    def validate_code(
        self,
        code: str,
        language: str = "python"
    ) -> CodeValidation:
        """
        Validate code for security issues.

        Checks for:
        - Dangerous imports/functions
        - System commands
        - Network access attempts
        """
        errors = []
        warnings = []

        if not code or not code.strip():
            errors.append("Empty code provided")
            return CodeValidation(is_valid=False, errors=errors, warnings=warnings)

        policy = SECURITY_POLICIES.get(language, SECURITY_POLICIES["python"])

        if language in ("python", "python3"):
            # Check for blocked imports
            blocked_imports = policy.get("blocked_imports", [])
            for blocked in blocked_imports:
                if blocked in code:
                    warnings.append(f"Potentially dangerous: '{blocked}' - will be blocked in sandbox")

            # Check for file operations (just warn, Docker handles this)
            if re.search(r'\bopen\s*\(', code):
                warnings.append("File operations may be restricted in sandbox")

            # Check for network operations
            if re.search(r'(requests|urllib|socket|http\.client)', code):
                warnings.append("Network access is disabled in sandbox")

            # Check for shell commands
            if re.search(r'(os\.system|subprocess|Popen)', code):
                warnings.append("Shell commands are restricted")

        elif language in ("bash", "shell"):
            blocked_commands = policy.get("blocked_commands", [])
            for blocked in blocked_commands:
                if blocked in code:
                    errors.append(f"Blocked command: '{blocked}'")

        return CodeValidation(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            sanitized_code=code,
        )

    async def run(
        self,
        code: str,
        language: str = "python",
        tier: ExecutionTier = ExecutionTier.STANDARD,
        validate: bool = True,
    ) -> ExecutionResult:
        """
        Execute code safely.

        Args:
            code: Code to execute
            language: Programming language
            tier: Resource limit tier
            validate: Whether to validate code first

        Returns:
            ExecutionResult with output and status
        """
        # Validate code
        if validate:
            validation = self.validate_code(code, language)
            if not validation.is_valid:
                return ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    output="",
                    error=f"Validation failed: {'; '.join(validation.errors)}",
                )

        # Get limits
        limits = get_limits(tier)

        # Execute via Docker if available
        if self._docker and self._docker.is_available:
            return await self._docker.execute(code, language, limits)

        # Fallback to restricted subprocess
        return await self._subprocess_execute(code, language, limits)

    async def _subprocess_execute(
        self,
        code: str,
        language: str,
        limits: ResourceLimits,
    ) -> ExecutionResult:
        """
        Fallback execution via subprocess (restricted).

        WARNING: Less secure than Docker. Only for development.
        """
        print("[CodeRunner] WARNING: Using subprocess fallback (less secure)")

        # Extra validation for subprocess mode
        validation = self.validate_code(code, language)
        if validation.warnings:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                output="",
                error=f"Subprocess mode blocked: {'; '.join(validation.warnings)}",
            )

        try:
            if language in ("python", "python3"):
                cmd = ["python3", "-c", code]
            elif language in ("node", "javascript"):
                cmd = ["node", "-e", code]
            elif language in ("bash", "shell"):
                cmd = ["sh", "-c", code]
            else:
                return ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    output="",
                    error=f"Unsupported language: {language}",
                )

            # Run with timeout
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=limits.timeout_seconds,
                )

                output = stdout.decode("utf-8")
                error_output = stderr.decode("utf-8")

                if process.returncode == 0:
                    return ExecutionResult(
                        status=ExecutionStatus.SUCCESS,
                        output=output,
                        error=error_output if error_output else None,
                        exit_code=0,
                    )
                else:
                    return ExecutionResult(
                        status=ExecutionStatus.ERROR,
                        output=output,
                        error=error_output or f"Exit code: {process.returncode}",
                        exit_code=process.returncode,
                    )

            except asyncio.TimeoutError:
                process.kill()
                return ExecutionResult(
                    status=ExecutionStatus.TIMEOUT,
                    output="",
                    error=f"Execution timed out after {limits.timeout_seconds}s",
                )

        except Exception as e:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                output="",
                error=str(e),
            )

    async def run_with_input(
        self,
        code: str,
        stdin_data: str,
        language: str = "python",
        tier: ExecutionTier = ExecutionTier.STANDARD,
    ) -> ExecutionResult:
        """
        Execute code with stdin input.

        Wraps the code to read from a variable instead of stdin.
        """
        if language in ("python", "python3"):
            # Wrap code to simulate stdin
            wrapped_code = f'''
import sys
from io import StringIO
sys.stdin = StringIO("""{stdin_data}""")

{code}
'''
            return await self.run(wrapped_code, language, tier)
        else:
            # For other languages, just run the code
            return await self.run(code, language, tier)

    def format_result(self, result: ExecutionResult) -> str:
        """Format execution result for display."""
        if result.status == ExecutionStatus.SUCCESS:
            return f"✅ Execution successful:\n```\n{result.output}\n```"
        elif result.status == ExecutionStatus.TIMEOUT:
            return f"⏱️ Execution timed out: {result.error}"
        else:
            output = f"❌ Execution failed"
            if result.error:
                output += f": {result.error}"
            if result.output:
                output += f"\n```\n{result.output}\n```"
            return output


# Singleton
_runner: Optional[CodeRunner] = None


async def get_code_runner() -> CodeRunner:
    """Get or create code runner instance."""
    global _runner

    if _runner is None:
        _runner = CodeRunner()
        await _runner.initialize()

    return _runner
