"""Configuration management for statusline."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_statusline.core.colors import parse_color

# Color config keys and which ColorManager slot they map to
_COLOR_KEYS: dict[str, str] = {
    "color_green": "green",
    "color_yellow": "yellow",
    "color_red": "red",
    "color_blue": "blue",
    "color_magenta": "magenta",
    "color_cyan": "cyan",
    # Per-property color keys
    "color_context_length": "context_length",
    "color_project_name": "project_name",
    "color_branch_name": "branch_name",
    "color_mi_score": "mi_score",
    "color_zone": "zone",
    "color_separator": "separator",
}

# Zone threshold config keys (integer token counts)
_ZONE_INT_KEYS: set[str] = {
    "zone_1m_plan_max",
    "zone_1m_code_max",
    "zone_1m_dump_max",
    "zone_1m_xdump_max",
    "zone_std_warn_buffer",
    "large_model_threshold",
}

# Zone threshold config keys (float ratios 0-1)
_ZONE_FLOAT_KEYS: set[str] = {
    "zone_std_dump_ratio",
    "zone_std_hard_limit",
    "zone_std_dead_ratio",
}


# ---------------------------------------------------------------------------
# Default config template — content aligned with examples/statusline.conf
# in the repository root.  Keep this string in sync when the example changes.
# ---------------------------------------------------------------------------
_DEFAULT_CONFIG_TEMPLATE = """\
# ============================================================================
# cc-context-stats — statusline configuration
# ============================================================================
#
# Copy this file to:   ~/.claude/statusline.conf
# Windows:             %USERPROFILE%\\.claude\\statusline.conf
#
# Full reference:
#   https://github.com/luongnv89/cc-context-stats/blob/main/docs/configuration.md
#
# Format:
#   - key=value (no spaces around '=')
#   - Lines starting with '#' are comments
#   - Unrecognized keys are silently ignored
#   - Missing or invalid values fall back to built-in defaults
#
# ============================================================================


# ─── Display Settings ───────────────────────────────────────────────────────
#
# These boolean flags control which elements appear in the statusline.
# Any value other than "false" (case-insensitive) is treated as true.

# Autocompact buffer display.
# When true, 22.5% of the context window is reserved for Claude Code's
# autocompact feature. This affects the "free tokens" calculation.
# Must match your Claude Code setting — check with: /config
#   true  -> shows [AC:45k] buffer in statusline
#   false -> shows [AC:off]
autocompact=false

# Token display format.
#   true  = exact count with commas (e.g., 64,000 free)
#   false = abbreviated with suffix  (e.g., 64.0k free)
# Also affects the delta display (+2,500 vs +2.5k).
token_detail=true

# Show token delta since last refresh (e.g., +2,500).
# Displays how many tokens were consumed since the previous statusline update.
# Requires file I/O on every refresh to read the previous state.
# Disable if you want to reduce disk overhead.
show_delta=true

# Show the session ID at the end of the statusline.
# Useful when running multiple Claude Code instances to identify sessions.
# Double-click in terminal to select and copy.
show_session=true

# Show input/output token breakdown.
# Reserved for future use — currently read but not displayed.
show_io_tokens=true

# Disable rotating text and icon animations for accessibility.
#   false = animations enabled (default)
#   true  = static display, no motion
reduced_motion=false


# ─── Model Intelligence (MI) ────────────────────────────────────────────────
#
# MI measures how effectively the model uses its context window. The score
# ranges from 0.000 (fully degraded) to 1.000 (optimal). As context fills,
# MI degrades following a model-specific curve.

# Show the MI score in the statusline (e.g., MI:0.918).
# When enabled, also requires state file I/O for tracking.
#   false = MI score hidden (default)
#   true  = MI score visible
show_mi=false

# Override the MI degradation curve beta for all models.
# Each model has a built-in profile that controls how quickly MI degrades:
#   opus   = 1.8  (retains quality longest, steep drop near end)
#   sonnet = 1.5  (moderate degradation)
#   haiku  = 1.2  (degrades earliest)
# Set to 0 to use the model-specific profile (recommended).
# Set a positive value (e.g., 1.5) to override for all models.
mi_curve_beta=0


# ─── Zone Threshold Overrides ───────────────────────────────────────────────
#
# Zones indicate how much context pressure your session is under:
#   Plan   (P) = plenty of room, ideal for planning and exploration
#   Code   (C) = normal coding zone, context is filling but healthy
#   Dump   (D) = getting full, consider wrapping up or starting fresh
#   ExDump (X) = critical, autocompact may trigger, quality degrading
#   Dead   (Z) = context exhausted, start a new session
#
# There are two threshold sets: one for large models (1M+ context) using
# absolute token counts, and one for standard models using ratios (0-1).
#
# Uncomment and set a positive value to override the built-in defaults.
# Invalid values (negative, non-numeric, ratios outside 0-1) are ignored
# with a warning to stderr.

# Context windows >= this value use 1M-class thresholds (token count).
# Models below this threshold use the standard ratio-based zones.
# large_model_threshold=500000

# --- 1M-Class Models (context >= large_model_threshold) ---
# Values are absolute token counts for zone boundaries (tokens used).
# zone_1m_plan_max=70000       # Plan -> Code boundary
# zone_1m_code_max=100000      # Code -> Dump boundary
# zone_1m_dump_max=250000      # Dump -> ExDump boundary
# zone_1m_xdump_max=275000     # ExDump -> Dead boundary

# --- Standard Models (context < large_model_threshold) ---
# Ratios are 0-1 fractions of the total context window.
# zone_std_dump_ratio=0.40     # Dump zone starts at 40% utilization
# zone_std_warn_buffer=30000   # Show warning this many tokens before dump zone
# zone_std_hard_limit=0.70     # Hard limit at 70% utilization
# zone_std_dead_ratio=0.75     # Dead zone starts at 75% utilization


# ─── Base Color Slots ───────────────────────────────────────────────────────
#
# Override the 6 base palette colors used for MI-based traffic-light coloring
# and as fallbacks for per-property colors (see next section).
#
# Accepts named colors or hex codes (#rrggbb).
#
# Named colors (18 available):
#   Standard:  black, red, green, yellow, blue, magenta, cyan, white
#   Bright:    bright_black, bright_red, bright_green, bright_yellow,
#              bright_blue, bright_magenta, bright_cyan, bright_white
#   Special:   bold_white, dim
#
# Hex colors: any #rrggbb value (requires 24-bit color terminal support)
#
# Unrecognized values are ignored with a warning to stderr.

# Traffic-light colors — used for MI score and context zone indicators.
# Colors are determined by BOTH MI score and context utilization:
#   color_green  -> MI >= 0.90 AND context < 40% (model operating well)
#   color_yellow -> MI in (0.80, 0.90) OR context in [40%, 80%) (pressure building)
#   color_red    -> MI <= 0.80 OR context >= 80% (significant degradation)
color_green=#7dcfff
color_yellow=#e0af68
color_red=#f7768e

# Legacy element fallback colors:
#   color_blue    -> fallback for project name (if color_project_name not set)
#   color_magenta -> fallback for branch name (if color_branch_name not set)
#   color_cyan    -> git change-count brackets (e.g., [3])
color_blue=#7aa2f7
color_magenta=#bb9af7
color_cyan=#2ac3de


# ─── Per-Property Colors ────────────────────────────────────────────────────
#
# Override individual statusline elements. These take precedence over
# base color slots above.
#
# Fallback chain: per-property key -> base color slot -> built-in default
#
# For example, if color_project_name is not set, it falls back to color_blue
# (if set), then to the built-in cyan.

# Context tokens remaining — the most critical info.
# When not set, uses zone traffic-light color (green/yellow/red) automatically.
# Set explicitly to use a fixed color regardless of zone.
# color_context_length=bold_white

# Project directory name (e.g., "my-project").
color_project_name=bright_cyan

# Git branch name (e.g., "main").
color_branch_name=bright_magenta

# MI score display (e.g., "MI:0.918").
# When not set, uses MI-based traffic-light color automatically.
color_mi_score=#ff9e64

# Zone indicator label (e.g., "Plan", "Code", "Dump").
# When not set, uses zone traffic-light color automatically.
# color_zone=bright_green

# Structural elements: model name, token delta, session ID.
# "dim" makes these visually recede so primary info stands out.
color_separator=dim


# ─── Statusline Layout Reference ────────────────────────────────────────────
#
# The statusline elements are displayed in this order (highest priority first):
#
#   project_name | branch [changes] | tokens_free (%) | Zone | MI:score | +delta | Model | session_id
#
# Example output:
#   my-project | main [3] | 64,000 free (32.0%) | Code | MI:0.918 | +2,500 | Opus 4.6 | abc-123
#
# If the terminal is too narrow, lower-priority elements are dropped:
#   1. session_id   (dropped first)
#   2. model name
#   3. token delta
#   4. MI score
#   5. zone indicator
#   6. context info
#   7. git info
#   8. project name  (always shown, never dropped)
"""


@dataclass
class Config:
    """Configuration settings for the statusline."""

    autocompact: bool = False
    token_detail: bool = True
    show_delta: bool = True
    show_session: bool = True
    show_io_tokens: bool = True
    reduced_motion: bool = False
    show_mi: bool = False
    mi_curve_beta: float = 0.0  # 0 = use model-specific profile default

    # Zone threshold overrides (0 = use defaults from intelligence.py)
    zone_1m_plan_max: int = 0
    zone_1m_code_max: int = 0
    zone_1m_dump_max: int = 0
    zone_1m_xdump_max: int = 0
    zone_std_dump_ratio: float = 0.0
    zone_std_warn_buffer: int = 0
    zone_std_hard_limit: float = 0.0
    zone_std_dead_ratio: float = 0.0
    large_model_threshold: int = 0

    # Custom color overrides (slot_name -> ANSI code)
    color_overrides: dict[str, str] = field(default_factory=dict)

    _config_path: Path = field(default_factory=lambda: Path.home() / ".claude" / "statusline.conf")

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Config:
        """Load configuration from file.

        Args:
            config_path: Path to config file. Defaults to ~/.claude/statusline.conf

        Returns:
            Config instance with loaded settings
        """
        config = cls()
        if config_path:
            config._config_path = Path(config_path).expanduser()

        if not config._config_path.exists():
            config._create_default()

        config._read_config()
        return config

    def _create_default(self) -> None:
        """Create default config file if it doesn't exist.

        Writes the canonical example configuration (aligned with
        examples/statusline.conf in the repository) to the user's
        config path.  If the file already exists, it is never overwritten.
        """
        if self._config_path.exists():
            return
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(
                _DEFAULT_CONFIG_TEMPLATE,
                encoding="utf-8",
            )
        except OSError as e:
            sys.stderr.write(
                f"[statusline] warning: failed to create config {self._config_path}: {e}\n"
            )

    def _read_config(self) -> None:
        """Read settings from config file."""
        try:
            content = self._config_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                raw_value = value.strip()
                value_lower = raw_value.lower()

                if key == "autocompact":
                    self.autocompact = value_lower != "false"
                elif key == "token_detail":
                    self.token_detail = value_lower != "false"
                elif key == "show_delta":
                    self.show_delta = value_lower != "false"
                elif key == "show_session":
                    self.show_session = value_lower != "false"
                elif key == "show_io_tokens":
                    self.show_io_tokens = value_lower != "false"
                elif key == "reduced_motion":
                    self.reduced_motion = value_lower != "false"
                elif key == "show_mi":
                    self.show_mi = value_lower != "false"
                elif key == "mi_curve_beta":
                    try:
                        self.mi_curve_beta = float(raw_value)
                    except ValueError:
                        pass
                elif key in _ZONE_INT_KEYS:
                    try:
                        v = int(raw_value)
                        if v > 0:
                            setattr(self, key, v)
                        else:
                            sys.stderr.write(
                                f"[statusline] warning: {key} must be positive, "
                                f"ignoring '{raw_value}'\n"
                            )
                    except ValueError:
                        sys.stderr.write(
                            f"[statusline] warning: invalid integer for {key}: "
                            f"'{raw_value}'\n"
                        )
                elif key in _ZONE_FLOAT_KEYS:
                    try:
                        v = float(raw_value)
                        if 0.0 < v < 1.0:
                            setattr(self, key, v)
                        else:
                            sys.stderr.write(
                                f"[statusline] warning: {key} must be between 0 and 1, "
                                f"ignoring '{raw_value}'\n"
                            )
                    except ValueError:
                        sys.stderr.write(
                            f"[statusline] warning: invalid number for {key}: "
                            f"'{raw_value}'\n"
                        )
                elif key in _COLOR_KEYS:
                    slot = _COLOR_KEYS[key]
                    ansi = parse_color(raw_value)
                    if ansi:
                        self.color_overrides[slot] = ansi
                    else:
                        sys.stderr.write(
                            f"[statusline] warning: unrecognized color value "
                            f"'{raw_value}' for {key}\n"
                        )
        except (OSError, UnicodeDecodeError) as e:
            sys.stderr.write(
                f"[statusline] warning: failed to read config {self._config_path}: {e}\n"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "autocompact": self.autocompact,
            "token_detail": self.token_detail,
            "show_delta": self.show_delta,
            "show_session": self.show_session,
            "show_io_tokens": self.show_io_tokens,
            "reduced_motion": self.reduced_motion,
            "show_mi": self.show_mi,
            "mi_curve_beta": self.mi_curve_beta,
            "zone_1m_plan_max": self.zone_1m_plan_max,
            "zone_1m_code_max": self.zone_1m_code_max,
            "zone_1m_dump_max": self.zone_1m_dump_max,
            "zone_1m_xdump_max": self.zone_1m_xdump_max,
            "zone_std_dump_ratio": self.zone_std_dump_ratio,
            "zone_std_warn_buffer": self.zone_std_warn_buffer,
            "zone_std_hard_limit": self.zone_std_hard_limit,
            "zone_std_dead_ratio": self.zone_std_dead_ratio,
            "large_model_threshold": self.large_model_threshold,
            "color_overrides": dict(self.color_overrides),
        }
