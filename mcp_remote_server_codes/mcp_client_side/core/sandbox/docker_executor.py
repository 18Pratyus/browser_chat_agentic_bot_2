"""
Docker Executor
===============
Manages Docker containers for safe code execution.

Features:
- Container lifecycle management
- Resource limit enforcement
- Output streaming
- Automatic cleanup
"""

import asyncio
import uuid
from typing import Optional, Dict, Any, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

try:
    import docker
    from docker.errors import ContainerError, ImageNotFound, APIError
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None

from .resource_limits import ResourceLimits, ExecutionTier, get_limits


class ExecutionStatus(str, Enum):
    """Status of code execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    KILLED = "killed"


@dataclass
class ExecutionResult:
    """Result of sandbox execution."""
    status: ExecutionStatus
    output: str
    error: Optional[str] = None
    exit_code: Optional[int] = None
    execution_time: float = 0.0
    container_id: Optional[str] = None
    memory_used: Optional[str] = None


class DockerExecutor:
    """
    Executes code safely in Docker containers.

    Provides isolated execution environment with:
    - Resource limits (CPU, memory, time)
    - Network isolation
    - Filesystem isolation
    - Automatic cleanup
    """

    # Supported language images
    IMAGES = {
        "python": "python:3.11-slim",
        "python3": "python:3.11-slim",
        "node": "node:20-slim",
        "javascript": "node:20-slim",
        "bash": "alpine:latest",
        "shell": "alpine:latest",
    }

    def __init__(self, default_limits: Optional[ResourceLimits] = None):
        """Initialize Docker executor."""
        self.default_limits = default_limits or get_limits(ExecutionTier.STANDARD)
        self._client = None
        self._available = False

    async def initialize(self) -> bool:
        """Initialize Docker client."""
        if not DOCKER_AVAILABLE:
            print("[DockerExecutor] Docker SDK not installed. Run: pip install docker")
            return False

        try:
            self._client = docker.from_env()
            # Test connection
            self._client.ping()
            self._available = True
            print("[DockerExecutor] Connected to Docker daemon")

            # Pull required images in background
            asyncio.create_task(self._ensure_images())

            return True
        except Exception as e:
            print(f"[DockerExecutor] Failed to connect to Docker: {e}")
            self._available = False
            return False

    async def _ensure_images(self):
        """Ensure required images are pulled."""
        for lang, image in self.IMAGES.items():
            try:
                self._client.images.get(image)
            except ImageNotFound:
                print(f"[DockerExecutor] Pulling image: {image}")
                try:
                    self._client.images.pull(image)
                    print(f"[DockerExecutor] Pulled: {image}")
                except Exception as e:
                    print(f"[DockerExecutor] Failed to pull {image}: {e}")

    @property
    def is_available(self) -> bool:
        """Check if Docker is available."""
        return self._available and self._client is not None

    async def execute(
        self,
        code: str,
        language: str = "python",
        limits: Optional[ResourceLimits] = None,
        env_vars: Optional[Dict[str, str]] = None,
        working_dir: str = "/workspace",
    ) -> ExecutionResult:
        """
        Execute code in a Docker container.

        Args:
            code: The code to execute
            language: Programming language (python, node, bash)
            limits: Resource limits (uses default if not provided)
            env_vars: Environment variables
            working_dir: Working directory inside container

        Returns:
            ExecutionResult with output, status, and metadata
        """
        if not self.is_available:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                output="",
                error="Docker is not available. Please install and start Docker.",
            )

        limits = limits or self.default_limits
        image = self.IMAGES.get(language, self.IMAGES["python"])
        container_id = f"sandbox_{uuid.uuid4().hex[:8]}"

        # Build command based on language
        command = self._build_command(code, language)

        start_time = datetime.now()
        container = None

        try:
            # Create and run container
            docker_config = limits.to_docker_config()

            container = self._client.containers.run(
                image=image,
                command=command,
                name=container_id,
                detach=True,
                remove=False,  # We'll remove manually after getting logs
                environment=env_vars or {},
                working_dir=working_dir,
                tmpfs={"/tmp": f"size={limits.tmpfs_size}"},
                **docker_config,
            )

            # Wait for completion with timeout
            try:
                result = container.wait(timeout=limits.timeout_seconds)
                exit_code = result.get("StatusCode", -1)

                # Get output
                logs = container.logs(stdout=True, stderr=True).decode("utf-8")

                # Determine status
                if exit_code == 0:
                    status = ExecutionStatus.SUCCESS
                    output = logs
                    error = None
                else:
                    status = ExecutionStatus.ERROR
                    output = logs
                    error = f"Process exited with code {exit_code}"

            except Exception as timeout_error:
                # Timeout - kill container
                try:
                    container.kill()
                except:
                    pass

                return ExecutionResult(
                    status=ExecutionStatus.TIMEOUT,
                    output="",
                    error=f"Execution timed out after {limits.timeout_seconds}s",
                    container_id=container_id,
                    execution_time=limits.timeout_seconds,
                )

            execution_time = (datetime.now() - start_time).total_seconds()

            # Get container stats for memory usage
            memory_used = None
            try:
                stats = container.stats(stream=False)
                memory_used = f"{stats['memory_stats'].get('usage', 0) / 1024 / 1024:.2f}MB"
            except:
                pass

            return ExecutionResult(
                status=status,
                output=output,
                error=error,
                exit_code=exit_code,
                execution_time=execution_time,
                container_id=container_id,
                memory_used=memory_used,
            )

        except ContainerError as e:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                output=e.stderr.decode("utf-8") if e.stderr else "",
                error=str(e),
                exit_code=e.exit_status,
                execution_time=(datetime.now() - start_time).total_seconds(),
            )

        except Exception as e:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                output="",
                error=f"Execution failed: {str(e)}",
                execution_time=(datetime.now() - start_time).total_seconds(),
            )

        finally:
            # Cleanup container
            if container:
                try:
                    container.remove(force=True)
                except:
                    pass

    def _build_command(self, code: str, language: str) -> list:
        """Build command for execution."""
        if language in ("python", "python3"):
            return ["python", "-c", code]
        elif language in ("node", "javascript"):
            return ["node", "-e", code]
        elif language in ("bash", "shell"):
            return ["sh", "-c", code]
        else:
            return ["python", "-c", code]

    async def execute_file(
        self,
        file_content: str,
        filename: str,
        language: str = "python",
        limits: Optional[ResourceLimits] = None,
    ) -> ExecutionResult:
        """
        Execute a file in sandbox.

        Creates a temp file inside container and executes it.
        """
        if not self.is_available:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                output="",
                error="Docker is not available.",
            )

        # Wrap code to write file and execute
        if language in ("python", "python3"):
            wrapper = f'''
import sys
code = """{file_content}"""
with open("/tmp/{filename}", "w") as f:
    f.write(code)
exec(open("/tmp/{filename}").read())
'''
            return await self.execute(wrapper, language, limits)
        else:
            return await self.execute(file_content, language, limits)

    async def cleanup_all(self):
        """Remove all sandbox containers."""
        if not self.is_available:
            return

        try:
            containers = self._client.containers.list(
                all=True,
                filters={"name": "sandbox_"}
            )
            for container in containers:
                try:
                    container.remove(force=True)
                except:
                    pass
            print(f"[DockerExecutor] Cleaned up {len(containers)} sandbox containers")
        except Exception as e:
            print(f"[DockerExecutor] Cleanup error: {e}")


# Singleton instance
_executor: Optional[DockerExecutor] = None


async def get_docker_executor() -> DockerExecutor:
    """Get or create Docker executor instance."""
    global _executor

    if _executor is None:
        _executor = DockerExecutor()
        await _executor.initialize()

    return _executor
