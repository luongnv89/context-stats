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

    Claude Code captures the statusline script's output rather than
    connecting it to a TTY, so ``shutil.get_terminal_size()`` cannot read
    the real width and falls back to 80. Since Claude Code v2.1.153, the
    harness exports ``COLUMNS`` (and ``LINES``) with the real terminal
    dimensions before running the script, so we trust ``COLUMNS`` when it
    is set. When it is absent (older Claude Code, or a non-TTY context
    where the width is genuinely undetectable), we use a generous default
    of 200 so the single line is not wrapped or truncated on a fallback
    artifact; Claude Code's own UI handles any overflow.
    """
    import os

    # If COLUMNS is explicitly set, trust it (real terminal, Claude Code
    # >= v2.1.153, or a test override).
    if os.environ.get("COLUMNS"):
        return shutil.get_terminal_size().columns
    # No COLUMNS env var — width is undetectable in this context.
    # shutil falls back to 80, which is too narrow. Use 200 instead.
    cols = shutil.get_terminal_size(fallback=(200, 24)).columns
    return 200 if cols == 80 else cols


# Separator that prefixes every part except the base. When a part starts a
# new line during reflow, this leading separator is stripped so wrapped
# lines do not begin with a dangling " | ".
_PART_SEPARATOR = " | "


def fit_to_width(parts: list[str], max_width: int) -> str:
    """Assemble parts into lines that each fit within max_width.

    Parts are packed greedily in priority order (first = highest priority).
    The first part (base) always starts the first line. Each subsequent
    part is appended to the current line when it fits; otherwise it starts
    a new line so no information is dropped on narrow terminals. Lines are
    joined with newlines, which Claude Code renders as separate rows.

    When all parts fit within ``max_width`` (e.g. the default width of 200),
    the result is a single line, byte-identical to the legacy single-line
    output. A part wider than ``max_width`` on its own is emitted whole on
    its own line rather than truncated. Empty parts are skipped.

    Args:
        parts: List of strings in priority order (highest first). Every
            part except the first is expected to begin with ``" | "``.
        max_width: Maximum visible width allowed per line.

    Returns:
        One or more lines joined by ``"\\n"`` with every part preserved.
    """
    if not parts:
        return ""

    lines: list[str] = []
    # Base part always starts the first line.
    current = parts[0]
    current_width = visible_width(current)

    for part in parts[1:]:
        if not part:
            continue
        part_width = visible_width(part)
        if current_width + part_width <= max_width:
            current += part
            current_width += part_width
        else:
            # Part does not fit — flush the current line and start a new
            # one with this part, stripping its leading separator so the
            # wrapped line does not begin with " | ".
            lines.append(current)
            if part.startswith(_PART_SEPARATOR):
                part = part[len(_PART_SEPARATOR) :]
            current = part
            current_width = visible_width(part)

    lines.append(current)
    return "\n".join(lines)
