"""Layout utilities for fitting statusline output to terminal width."""

from __future__ import annotations

import re
import shutil

# Pattern to strip ANSI escape sequences
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_width(s: str) -> int:
    """Return the visible width of a string after stripping ANSI escape sequences."""
    return len(_ANSI_RE.sub("", s))


def get_terminal_width() -> int:
    """Return the terminal width in columns.

    When running inside Claude Code's statusline subprocess, neither $COLUMNS
    nor tput/shutil can detect the real terminal width (they always return 80).
    If COLUMNS is not explicitly set and shutil falls back to 80, we use a
    generous default of 200 so that no parts are unnecessarily dropped;
    Claude Code's own UI handles any overflow/truncation.
    """
    import os

    # If COLUMNS is explicitly set, trust it (real terminal or test override)
    if os.environ.get("COLUMNS"):
        return shutil.get_terminal_size().columns
    # No COLUMNS env var — likely a Claude Code subprocess with no real TTY.
    # shutil will fall back to 80, which is too narrow. Use 200 instead.
    cols = shutil.get_terminal_size(fallback=(200, 24)).columns
    return 200 if cols == 80 else cols


def fit_to_width(parts: list[str], max_width: int) -> str:
    """Assemble parts into a single line that fits within max_width.

    Parts are added in priority order (first = highest priority).
    The first part (base) is always included. Subsequent parts are
    included only if adding them does not exceed max_width.
    Empty parts are skipped.

    Args:
        parts: List of strings in priority order (highest first).
        max_width: Maximum visible width allowed.

    Returns:
        Assembled string that fits within max_width.
    """
    if not parts:
        return ""

    # Base part is always included
    result = parts[0]
    current_width = visible_width(result)

    for part in parts[1:]:
        if not part:
            continue
        part_width = visible_width(part)
        if current_width + part_width <= max_width:
            result += part
            current_width += part_width

    return result
