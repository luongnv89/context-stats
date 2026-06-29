"""Git integration utilities."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from claude_statusline.core.colors import CYAN, MAGENTA, RESET, ColorManager

# PR-number lookups shell out to ``gh`` (a network call). Because the
# statusline re-renders frequently, the result is cached per-branch for a
# short TTL so the network round-trip happens at most once per window.
_PR_CACHE_TTL_SECONDS = 60


def _pr_cache_file() -> Path:
    """Location of the shared PR-number cache file."""
    return Path.home() / ".claude" / "statusline" / "pr_number_cache.json"


def _pr_cache_get(key: str) -> str | None:
    """Return the cached PR string for ``key`` if present and unexpired.

    Returns ``None`` on any miss (no entry, expired, or read error) so the
    caller falls through to a live lookup. Never raises.
    """
    try:
        with open(_pr_cache_file(), encoding="utf-8") as fh:
            cache = json.load(fh)
        entry = cache.get(key)
        if isinstance(entry, dict) and entry.get("exp", 0) > time.time():
            return str(entry.get("pr", ""))
    except (OSError, ValueError):
        pass
    return None


def _pr_cache_set(key: str, pr: str) -> None:
    """Store ``pr`` for ``key`` with a TTL, pruning expired entries.

    Best-effort and atomic: any IO error is swallowed so a render never fails
    on a cache write.
    """
    try:
        path = _pr_cache_file()
        now = time.time()
        try:
            with open(path, encoding="utf-8") as fh:
                cache = json.load(fh)
            if not isinstance(cache, dict):
                cache = {}
        except (OSError, ValueError):
            cache = {}
        cache = {k: v for k, v in cache.items() if isinstance(v, dict) and v.get("exp", 0) > now}
        cache[key] = {"pr": pr, "exp": now + _PR_CACHE_TTL_SECONDS}
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(cache, fh)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except OSError:
        pass


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

        cache_key = f"{project_dir}\t{branch_name}"
        cached = _pr_cache_get(cache_key)
        if cached is not None:
            return cached

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

        pr_str = ""
        if data and len(data) > 0:
            pr_num = data[0].get("number", "")
            if pr_num:
                pr_str = f"#{pr_num}"
        _pr_cache_set(cache_key, pr_str)
        return pr_str
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
