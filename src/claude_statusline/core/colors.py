"""ANSI color constants and utilities."""

from __future__ import annotations

# Single-sourced in _shared (Task 5.2, F-DEAD-001): the standalone script loads
# the same bodies from claude_statusline._shared / its vendored copy.
from claude_statusline._shared import BLUE, BOLD, CYAN, DIM, GREEN, MAGENTA, RED, RESET, YELLOW
from claude_statusline._shared import COLOR_NAMES as COLOR_NAMES
from claude_statusline._shared import (
    ZONE_AMBER_ANSI as ZONE_AMBER_ANSI,
)
from claude_statusline._shared import (
    ZONE_DARK_RED_ANSI as ZONE_DARK_RED_ANSI,
)
from claude_statusline._shared import (
    ZONE_GRAY_ANSI as ZONE_GRAY_ANSI,
)
from claude_statusline._shared import (
    ZONE_ORANGE_ANSI as ZONE_ORANGE_ANSI,
)
from claude_statusline._shared import parse_color as parse_color

# Structural segment separators (Task 5.6, F-CLEAN-008): single home for the
# literal glue the statusline segments are assembled from, so the CLI layer
# carries no formatting literals.
SEGMENT_SEPARATOR = " | "
INLINE_SEPARATOR = "·"


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

    def _get_structural(self, slot: str) -> str:
        """Structural elements default to the separator color, but each can be
        overridden independently (color_tps / color_delta / color_model /
        color_session)."""
        if not self.enabled:
            return ""
        if slot in self._overrides:
            return self._overrides[slot]
        return self.separator

    @property
    def tps(self) -> str:
        return self._get_structural("tps")

    @property
    def delta(self) -> str:
        return self._get_structural("delta")

    @property
    def cost(self) -> str:
        return self._get_structural("cost")

    @property
    def model(self) -> str:
        return self._get_structural("model")

    @property
    def session(self) -> str:
        return self._get_structural("session")

    @property
    def bold(self) -> str:
        return BOLD if self.enabled else ""

    @property
    def dim(self) -> str:
        return DIM if self.enabled else ""

    @property
    def reset(self) -> str:
        return RESET if self.enabled else ""

    def zone_color(self, color_name: str) -> str:
        """Traffic-light ANSI for a zone color name (Task 5.6, F-CLEAN-008).

        Maps the zone indicator's ``color`` field ("green", "yellow",
        "orange", "dark_red", "gray") to its ANSI sequence: green/yellow go
        through the override-aware slots, orange/dark_red/gray use the fixed
        shared RGB constants. Unknown names fall back to the reset code.
        Returns "" entirely when colors are disabled.
        """
        if color_name == "green":
            return self.green
        if color_name == "yellow":
            return self.yellow
        fixed = {
            "orange": ZONE_ORANGE_ANSI,
            "amber": ZONE_AMBER_ANSI,
            "dark_red": ZONE_DARK_RED_ANSI,
            "gray": ZONE_GRAY_ANSI,
        }
        if color_name in fixed:
            return fixed[color_name] if self.enabled else ""
        return self.reset
