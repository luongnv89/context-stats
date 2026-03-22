"""ANSI color constants and utilities."""

from __future__ import annotations

import re

# ANSI color codes (defaults)
BLUE = "\033[0;34m"
MAGENTA = "\033[0;35m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# Mapping from color names to ANSI codes
COLOR_NAMES: dict[str, str] = {
    "black": "\033[0;30m",
    "red": "\033[0;31m",
    "green": "\033[0;32m",
    "yellow": "\033[0;33m",
    "blue": "\033[0;34m",
    "magenta": "\033[0;35m",
    "cyan": "\033[0;36m",
    "white": "\033[0;37m",
    "bright_black": "\033[0;90m",
    "bright_red": "\033[0;91m",
    "bright_green": "\033[0;92m",
    "bright_yellow": "\033[0;93m",
    "bright_blue": "\033[0;94m",
    "bright_magenta": "\033[0;95m",
    "bright_cyan": "\033[0;96m",
    "bright_white": "\033[0;97m",
    "bold_white": "\033[1;97m",
    "dim": "\033[2m",
}

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


def parse_color(value: str) -> str | None:
    """Parse a color value into an ANSI escape code.

    Accepts:
      - Named colors: "red", "green", "bright_cyan", etc.
      - Hex colors: "#ff5733" (converted to 24-bit ANSI)

    Returns:
        ANSI escape code string, or None if the value is not recognized.
    """
    value = value.strip().lower()
    if not value:
        return None

    # Named color
    if value in COLOR_NAMES:
        return COLOR_NAMES[value]

    # Hex color (#rrggbb)
    m = _HEX_RE.match(value)
    if m:
        hex_str = m.group(1)
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"

    return None


class ColorManager:
    """Manage color output based on terminal capabilities.

    Supports custom color overrides via a dict of {slot_name: ansi_code}.
    """

    def __init__(
        self,
        enabled: bool = True,
        overrides: dict[str, str] | None = None,
    ) -> None:
        self.enabled = enabled
        self._overrides = overrides or {}

    def _get(self, slot: str, default: str) -> str:
        if not self.enabled:
            return ""
        return self._overrides.get(slot, default)

    @property
    def blue(self) -> str:
        return self._get("blue", BLUE)

    @property
    def magenta(self) -> str:
        return self._get("magenta", MAGENTA)

    @property
    def cyan(self) -> str:
        return self._get("cyan", CYAN)

    @property
    def green(self) -> str:
        return self._get("green", GREEN)

    @property
    def yellow(self) -> str:
        return self._get("yellow", YELLOW)

    @property
    def red(self) -> str:
        return self._get("red", RED)

    def _get_prop(self, slot: str, fallback_slot: str, default: str) -> str:
        """Get per-property color with fallback to old color key, then default."""
        if not self.enabled:
            return ""
        if slot in self._overrides:
            return self._overrides[slot]
        if fallback_slot in self._overrides:
            return self._overrides[fallback_slot]
        return default

    # Per-property color slots
    # Cascade: per-property key -> old color key -> highlighted default
    @property
    def context_length(self) -> str:
        return self._get("context_length", "\033[1;97m" if self.enabled else "")

    @property
    def project_name(self) -> str:
        return self._get_prop("project_name", "blue", CYAN)

    @property
    def branch_name(self) -> str:
        return self._get_prop("branch_name", "magenta", GREEN)

    @property
    def mi_score(self) -> str:
        return self._get("mi_score", YELLOW if self.enabled else "")

    @property
    def zone(self) -> str:
        return self._get("zone", "" if self.enabled else "")

    @property
    def separator(self) -> str:
        return self._get("separator", DIM if self.enabled else "")

    @property
    def bold(self) -> str:
        return BOLD if self.enabled else ""

    @property
    def dim(self) -> str:
        return DIM if self.enabled else ""

    @property
    def reset(self) -> str:
        return RESET if self.enabled else ""
