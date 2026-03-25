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


@dataclass
class Config:
    """Configuration settings for the statusline."""

    autocompact: bool = True
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
            return config

        config._read_config()
        return config

    def _create_default(self) -> None:
        """Create default config file if it doesn't exist."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(
                """# cc-context-stats — statusline configuration
# Full reference: https://github.com/luongnv89/cc-context-stats/blob/main/docs/configuration.md

# ─── Display Settings ───────────────────────────────────────────────

# Autocompact setting — sync with Claude Code's /config
# When true, 22.5% of the context window is reserved for the autocompact buffer.
autocompact=true

# Token display format
# true  = exact count (e.g., 64,000)
# false = abbreviated  (e.g., 64.0k)
token_detail=true

# Show token delta since last refresh (e.g., +2,500)
# Adds file I/O on every refresh; disable if you don't need it
show_delta=true

# Show session_id in the status line
show_session=true

# Show input/output token breakdown (reserved for future use)
show_io_tokens=true

# Disable rotating text animations (accessibility)
reduced_motion=false

# ─── Model Intelligence (MI) ────────────────────────────────────────

# Show the MI score in the status line
show_mi=false

# MI curve beta override (0 = use model-specific profile)
# Per-model defaults: opus=1.8, sonnet=1.5, haiku=1.2
# Set a positive value to override for all models (e.g., 1.5)
mi_curve_beta=0

# ─── Zone Threshold Overrides ───────────────────────────────────────
# Uncomment and set a positive value to override the built-in defaults.
# Omitted or commented-out keys use the defaults shown below.

# Context windows >= this value use 1M-class thresholds (token count)
# large_model_threshold=500000

# 1M-class models (context >= large_model_threshold)
# Values are token counts for zone boundaries
# zone_1m_plan_max=70000
# zone_1m_code_max=100000
# zone_1m_dump_max=250000
# zone_1m_xdump_max=275000

# Standard models (context < large_model_threshold)
# Ratios are 0–1 fractions of the context window; warn_buffer is a token count
# zone_std_dump_ratio=0.40
# zone_std_warn_buffer=30000
# zone_std_hard_limit=0.70
# zone_std_dead_ratio=0.75

# ─── Base Color Slots ───────────────────────────────────────────────
# Override the MI/context traffic-light colors and legacy element colors.
# Accepts named colors or hex codes (#rrggbb).
#
# Named colors: black, red, green, yellow, blue, magenta, cyan, white,
#   bright_black, bright_red, bright_green, bright_yellow,
#   bright_blue, bright_magenta, bright_cyan, bright_white,
#   bold_white, dim
#
# color_green=green
# color_yellow=yellow
# color_red=red
# color_blue=blue
# color_magenta=magenta
# color_cyan=cyan

# ─── Per-Property Colors ────────────────────────────────────────────
# Override individual statusline elements. These take precedence over
# base color slots. Unset keys fall back to the base slot or built-in.
#
# color_context_length=bold_white
# color_project_name=cyan
# color_branch_name=green
# color_mi_score=yellow
# color_zone=default
# color_separator=dim
"""
            )
        except OSError as e:
            sys.stderr.write(
                f"[statusline] warning: failed to create config {self._config_path}: {e}\n"
            )

    def _read_config(self) -> None:
        """Read settings from config file."""
        try:
            content = self._config_path.read_text()
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
