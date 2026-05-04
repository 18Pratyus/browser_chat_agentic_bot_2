"""
File Bridge
===========
Secure file I/O between host and sandbox.

Features:
- Controlled file sharing
- Size limits
- Content validation
- Temporary workspace management
"""

import os
import uuid
import shutil
import tempfile
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class FileEntry:
    """A file in the sandbox workspace."""
    id: str
    filename: str
    size: int
    content_type: str
    created_at: datetime
    expires_at: datetime
    host_path: str


@dataclass
class WorkspaceConfig:
    """Configuration for sandbox workspace."""
    max_file_size: int = 10 * 1024 * 1024    # 10MB per file
    max_total_size: int = 100 * 1024 * 1024  # 100MB total
    max_files: int = 50                       # Max files per workspace
    file_ttl_hours: int = 24                  # File expiration
    allowed_extensions: List[str] = field(default_factory=lambda: [
        ".py", ".js", ".ts", ".json", ".txt", ".csv", ".md",
        ".yaml", ".yml", ".toml", ".ini", ".xml", ".html", ".css",
    ])
    blocked_extensions: List[str] = field(default_factory=lambda: [
        ".exe", ".dll", ".so", ".dylib", ".sh", ".bat", ".cmd",
        ".php", ".jsp", ".asp", ".war", ".jar",
    ])


class FileBridge:
    """
    Manages file transfer between host and sandbox.

    Provides:
    - Secure file upload to workspace
    - File download from sandbox
    - Workspace cleanup
    - Size and type validation
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        config: Optional[WorkspaceConfig] = None,
    ):
        """
        Initialize file bridge.

        Args:
            base_dir: Base directory for workspaces (uses temp dir if not provided)
            config: Workspace configuration
        """
        self.config = config or WorkspaceConfig()

        if base_dir:
            self.base_dir = Path(base_dir)
            self.base_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.base_dir = Path(tempfile.gettempdir()) / "sandbox_workspaces"
            self.base_dir.mkdir(parents=True, exist_ok=True)

        # Track workspaces: workspace_id -> {files: Dict[str, FileEntry], path: Path}
        self._workspaces: Dict[str, Dict[str, Any]] = {}

    def create_workspace(self, workspace_id: Optional[str] = None) -> str:
        """
        Create a new isolated workspace.

        Returns:
            Workspace ID
        """
        workspace_id = workspace_id or f"ws_{uuid.uuid4().hex[:12]}"
        workspace_path = self.base_dir / workspace_id
        workspace_path.mkdir(parents=True, exist_ok=True)

        self._workspaces[workspace_id] = {
            "files": {},
            "path": workspace_path,
            "created_at": datetime.utcnow(),
            "total_size": 0,
        }

        print(f"[FileBridge] Created workspace: {workspace_id}")
        return workspace_id

    def get_workspace_path(self, workspace_id: str) -> Optional[Path]:
        """Get the host path for a workspace."""
        ws = self._workspaces.get(workspace_id)
        return ws["path"] if ws else None

    def add_file(
        self,
        workspace_id: str,
        filename: str,
        content: bytes,
        content_type: str = "text/plain",
    ) -> Optional[FileEntry]:
        """
        Add a file to workspace.

        Args:
            workspace_id: Target workspace
            filename: File name
            content: File content as bytes
            content_type: MIME type

        Returns:
            FileEntry or None if validation fails
        """
        ws = self._workspaces.get(workspace_id)
        if not ws:
            print(f"[FileBridge] Workspace not found: {workspace_id}")
            return None

        # Validate filename
        ext = os.path.splitext(filename)[1].lower()
        if ext in self.config.blocked_extensions:
            print(f"[FileBridge] Blocked extension: {ext}")
            return None

        if self.config.allowed_extensions and ext not in self.config.allowed_extensions:
            print(f"[FileBridge] Extension not allowed: {ext}")
            return None

        # Validate size
        file_size = len(content)
        if file_size > self.config.max_file_size:
            print(f"[FileBridge] File too large: {file_size} > {self.config.max_file_size}")
            return None

        if ws["total_size"] + file_size > self.config.max_total_size:
            print(f"[FileBridge] Workspace size limit exceeded")
            return None

        # Validate file count
        if len(ws["files"]) >= self.config.max_files:
            print(f"[FileBridge] Max files exceeded: {self.config.max_files}")
            return None

        # Sanitize filename
        safe_filename = self._sanitize_filename(filename)
        file_id = f"f_{uuid.uuid4().hex[:8]}"
        host_path = ws["path"] / safe_filename

        # Write file
        try:
            host_path.write_bytes(content)
        except Exception as e:
            print(f"[FileBridge] Write error: {e}")
            return None

        # Create entry
        now = datetime.utcnow()
        entry = FileEntry(
            id=file_id,
            filename=safe_filename,
            size=file_size,
            content_type=content_type,
            created_at=now,
            expires_at=now + timedelta(hours=self.config.file_ttl_hours),
            host_path=str(host_path),
        )

        ws["files"][file_id] = entry
        ws["total_size"] += file_size

        print(f"[FileBridge] Added file: {safe_filename} ({file_size} bytes)")
        return entry

    def add_text_file(
        self,
        workspace_id: str,
        filename: str,
        content: str,
    ) -> Optional[FileEntry]:
        """Add a text file to workspace."""
        return self.add_file(
            workspace_id,
            filename,
            content.encode("utf-8"),
            "text/plain",
        )

    def get_file(
        self,
        workspace_id: str,
        file_id: str,
    ) -> Optional[bytes]:
        """Get file content from workspace."""
        ws = self._workspaces.get(workspace_id)
        if not ws:
            return None

        entry = ws["files"].get(file_id)
        if not entry:
            return None

        try:
            return Path(entry.host_path).read_bytes()
        except Exception as e:
            print(f"[FileBridge] Read error: {e}")
            return None

    def list_files(self, workspace_id: str) -> List[FileEntry]:
        """List all files in workspace."""
        ws = self._workspaces.get(workspace_id)
        if not ws:
            return []
        return list(ws["files"].values())

    def remove_file(self, workspace_id: str, file_id: str) -> bool:
        """Remove a file from workspace."""
        ws = self._workspaces.get(workspace_id)
        if not ws:
            return False

        entry = ws["files"].get(file_id)
        if not entry:
            return False

        try:
            Path(entry.host_path).unlink(missing_ok=True)
            ws["total_size"] -= entry.size
            del ws["files"][file_id]
            return True
        except Exception as e:
            print(f"[FileBridge] Remove error: {e}")
            return False

    def cleanup_workspace(self, workspace_id: str) -> bool:
        """Remove workspace and all its files."""
        ws = self._workspaces.get(workspace_id)
        if not ws:
            return False

        try:
            shutil.rmtree(ws["path"], ignore_errors=True)
            del self._workspaces[workspace_id]
            print(f"[FileBridge] Cleaned up workspace: {workspace_id}")
            return True
        except Exception as e:
            print(f"[FileBridge] Cleanup error: {e}")
            return False

    def cleanup_expired(self) -> int:
        """Remove expired files across all workspaces."""
        now = datetime.utcnow()
        removed = 0

        for ws_id, ws in list(self._workspaces.items()):
            for file_id, entry in list(ws["files"].items()):
                if entry.expires_at < now:
                    if self.remove_file(ws_id, file_id):
                        removed += 1

            # Remove empty workspaces
            if not ws["files"]:
                self.cleanup_workspace(ws_id)

        if removed:
            print(f"[FileBridge] Cleaned up {removed} expired files")
        return removed

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for security."""
        # Remove path separators
        filename = os.path.basename(filename)

        # Remove dangerous characters
        filename = "".join(c for c in filename if c.isalnum() or c in "._-")

        # Limit length
        if len(filename) > 255:
            name, ext = os.path.splitext(filename)
            filename = name[:255-len(ext)] + ext

        return filename or "unnamed"


# Singleton
_file_bridge: Optional[FileBridge] = None


def get_file_bridge() -> FileBridge:
    """Get or create file bridge instance."""
    global _file_bridge

    if _file_bridge is None:
        _file_bridge = FileBridge()

    return _file_bridge
