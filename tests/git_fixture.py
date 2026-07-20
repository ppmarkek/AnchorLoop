from __future__ import annotations

import subprocess
from pathlib import Path


def init_git_repository(root: Path) -> None:
    """Initialize the minimal Git worktree required by actual-diff checks."""
    if (root / ".git").exists():
        return
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
