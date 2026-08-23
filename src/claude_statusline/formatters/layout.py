"""Layout utilities for fitting statusline output to terminal width."""

from __future__ import annotations

# Single-sourced in _shared (Task 5.2, F-DEAD-001); the standalone script loads
# the same bodies from claude_statusline._shared / its vendored copy.
from claude_statusline._shared import _ANSI_RE as _ANSI_RE
from claude_statusline._shared import _PART_SEPARATOR as _PART_SEPARATOR
from claude_statusline._shared import fit_to_width as fit_to_width
from claude_statusline._shared import get_terminal_width as get_terminal_width
from claude_statusline._shared import visible_width as visible_width
