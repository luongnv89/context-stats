"""Git integration utilities."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from claude_statusline.core.colors import CYAN, MAGENTA, RESET, ColorManager


def _get_pr_number(project_dir: Path) -> str:
    """Look up the PR number for the current branch via gh CLI.

    Returns a formatted string like ``#42`` when an open PR exists,
    or an empty string when no PR is associated or gh CLI is unavailable.
    """
    if shutil.which("gh") is None:
        return ""

    try:
        branch = subprocess.run(
            ["git", "--no-optional-locks", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch.returncode != 0:
            return ""
        branch_name = branch.stdout.strip()
        if not branch_name:
            return ""

        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch_name,
                "--state",
                "open",
                "--json",
                "number",
                "--limit",
                "1",
            ],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ""

        try:
            data = json.loads(result.stdout.strip())
        except (json.JSONDecodeError, ValueError):
            return ""

        if data and len(data) > 0:
            pr_num = data[0].get("number", "")
            if pr_num:
                return f"#{pr_num}"
        return ""
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return ""


def get_git_info(
    project_dir: str | Path,
    colors_enabled: bool = True,
    color_manager: ColorManager | None = None,
) -> str:
    """Get git branch and change count for a directory.

    Args:
        project_dir: Path to the project directory
        colors_enabled: Whether to include ANSI color codes. Deprecated —
            prefer passing a ColorManager via color_manager instead.
        color_manager: Optional ColorManager for custom colors. If provided,
            colors_enabled is ignored (the manager handles that).

    Returns:
        Formatted string with branch and change count, or empty string if not a git repo
    """
    project_dir = Path(project_dir)
    git_dir = project_dir / ".git"

    if not git_dir.is_dir():
        return ""

    try:
        # Get branch name (skip optional locks for performance)
        result = subprocess.run(
            ["git", "--no-optional-locks", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ""
        branch = result.stdout.strip()

        if not branch:
            return ""

        # Count changes
        result = subprocess.run(
            ["git", "--no-optional-locks", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            changes = 0
        else:
            changes = len([line for line in result.stdout.split("\n") if line.strip()])

        # Format output — use ColorManager if provided, else fallback to constants
        if color_manager is not None:
            magenta = color_manager.magenta
            cyan = color_manager.cyan
            reset = color_manager.reset
        elif colors_enabled:
            magenta, cyan, reset = MAGENTA, CYAN, RESET
        else:
            magenta = cyan = reset = ""

        if changes > 0:
            return f" | {magenta}{branch}{reset} {cyan}[{changes}]{reset}"
        return f" | {magenta}{branch}{reset}"

    except (subprocess.TimeoutExpired, OSError):
        return ""
