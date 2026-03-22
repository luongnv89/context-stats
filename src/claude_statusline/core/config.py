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
                """# Autocompact setting - sync with Claude Code's /config
autocompact=true

# Token display format
token_detail=true

# Show token delta since last refresh (adds file I/O on every refresh)
# Disable if you don't need it to reduce overhead
show_delta=true

# Show session_id in status line
show_session=true

# Disable rotating text animations
reduced_motion=false

# Model Intelligence (MI) score display
show_mi=false

# MI curve beta override (0 = use model-specific profile)
# Set to override the per-model default (e.g., 1.5 for moderate decay)
# mi_curve_beta=0

# Custom colors - use named colors or hex (#rrggbb)
# Available color slots: color_green, color_yellow, color_red,
#   color_blue, color_magenta, color_cyan
# Named colors: black, red, green, yellow, blue, magenta, cyan, white,
#   bright_black, bright_red, bright_green, bright_yellow,
#   bright_blue, bright_magenta, bright_cyan, bright_white,
#   bold_white, dim
# Examples:
#   color_green=#7dcfff
#   color_yellow=bright_yellow
#   color_red=#f7768e

# Per-property colors (override individual statusline elements)
# Defaults highlight key info: context=bold_white, project=cyan, branch=green
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
            "color_overrides": dict(self.color_overrides),
        }
