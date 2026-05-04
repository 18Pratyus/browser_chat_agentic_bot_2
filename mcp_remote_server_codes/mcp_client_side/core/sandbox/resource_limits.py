"""
Resource Limits Configuration
=============================
Defines CPU, memory, and time limits for sandbox execution.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum


class ExecutionTier(str, Enum):
    """Execution tiers with different resource allocations."""
    MINIMAL = "minimal"      # Quick scripts, low resources
    STANDARD = "standard"    # Normal execution
    INTENSIVE = "intensive"  # Data processing, ML tasks
    CUSTOM = "custom"        # User-defined limits


@dataclass
class ResourceLimits:
    """Resource limits for sandbox execution."""

    # Memory limits
    memory_limit: str = "256m"          # Docker memory limit (e.g., "256m", "1g")
    memory_swap: str = "512m"           # Memory + swap limit

    # CPU limits
    cpu_period: int = 100000            # CPU period in microseconds
    cpu_quota: int = 50000              # CPU quota (50000 = 50% of one CPU)
    cpu_count: Optional[float] = 1.0    # Number of CPUs

    # Time limits
    timeout_seconds: int = 30           # Execution timeout

    # Network
    network_disabled: bool = True       # Disable network access

    # Filesystem
    read_only: bool = True              # Read-only root filesystem
    tmpfs_size: str = "64m"             # Temp filesystem size

    # Security
    privileged: bool = False            # Never run privileged
    cap_drop: list = field(default_factory=lambda: ["ALL"])  # Drop all capabilities

    # Process limits
    pids_limit: int = 50                # Max processes

    def to_docker_config(self) -> Dict[str, Any]:
        """Convert to Docker container config."""
        return {
            "mem_limit": self.memory_limit,
            "memswap_limit": self.memory_swap,
            "cpu_period": self.cpu_period,
            "cpu_quota": self.cpu_quota,
            "nano_cpus": int(self.cpu_count * 1e9) if self.cpu_count else None,
            "network_disabled": self.network_disabled,
            "read_only": self.read_only,
            "privileged": self.privileged,
            "cap_drop": self.cap_drop,
            "pids_limit": self.pids_limit,
        }


# Predefined limit profiles
LIMIT_PROFILES: Dict[ExecutionTier, ResourceLimits] = {
    ExecutionTier.MINIMAL: ResourceLimits(
        memory_limit="128m",
        memory_swap="256m",
        cpu_quota=25000,        # 25% CPU
        timeout_seconds=10,
        pids_limit=20,
    ),
    ExecutionTier.STANDARD: ResourceLimits(
        memory_limit="256m",
        memory_swap="512m",
        cpu_quota=50000,        # 50% CPU
        timeout_seconds=30,
        pids_limit=50,
    ),
    ExecutionTier.INTENSIVE: ResourceLimits(
        memory_limit="1g",
        memory_swap="2g",
        cpu_quota=100000,       # 100% CPU (1 core)
        cpu_count=2.0,
        timeout_seconds=120,
        pids_limit=100,
    ),
}


def get_limits(tier: ExecutionTier = ExecutionTier.STANDARD) -> ResourceLimits:
    """Get resource limits for a tier."""
    return LIMIT_PROFILES.get(tier, LIMIT_PROFILES[ExecutionTier.STANDARD])


# Security policies for different code types
SECURITY_POLICIES = {
    "python": {
        "blocked_imports": [
            "os.system", "subprocess", "shutil.rmtree",
            "socket", "urllib", "requests", "http.client",
            "__import__", "eval", "exec", "compile",
        ],
        "blocked_builtins": [
            "open",  # File access (use file_bridge instead)
            "input",  # Interactive input not supported
        ],
    },
    "shell": {
        "blocked_commands": [
            "rm -rf", "dd", "mkfs", "fdisk",
            "curl", "wget", "nc", "netcat",
            "ssh", "scp", "rsync",
        ],
    },
}
