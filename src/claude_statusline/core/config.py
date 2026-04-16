"""Configuration management for statusline."""

from __future__ import annotations

import importlib.resources
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

# Compaction-related float config keys (fractions in (0, 1))
_COMPACTION_FLOAT_KEYS: set[str] = {
    "compaction_drop_threshold",
    "compact_mi_warn_threshold",
}


# ---------------------------------------------------------------------------
# Default config template — loaded at runtime from package data
# (data/statusline.conf.default), with a minimal fallback for non-standard
# installs where the resource cannot be found.
# ---------------------------------------------------------------------------

_MINIMAL_CONFIG_FALLBACK = """\
# context-stats — statusline configuration
# Full reference: https://github.com/luongnv89/cc-context-stats/blob/main/docs/configuration.md
autocompact=false
token_detail=true
show_delta=true
show_session=true
show_io_tokens=true
reduced_motion=false
show_mi=false
mi_curve_beta=0
"""


def _load_default_config_template() -> str:
    """Load the default config template from package data.

    Reads ``data/statusline.conf.default`` bundled inside the
    ``claude_statusline`` package.  Falls back to a minimal inline
    template when the resource cannot be located (e.g. running from a
    non-standard install or the data file is missing).
    """
    try:
        ref = importlib.resources.files("claude_statusline.data").joinpath(
            "statusline.conf.default"
        )
        return ref.read_text(encoding="utf-8")
    except Exception:
        return _MINIMAL_CONFIG_FALLBACK


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

    # Compaction detection settings
    compaction_drop_threshold: float = 0.5  # drop fraction to qualify as compaction
    compact_mi_warn_threshold: float = 0.6  # MI below this at compact time → warning

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

        if config._config_path.exists():
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
                _load_default_config_template(),
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
                            f"[statusline] warning: invalid integer for {key}: '{raw_value}'\n"
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
                            f"[statusline] warning: invalid number for {key}: '{raw_value}'\n"
                        )
                elif key in _COMPACTION_FLOAT_KEYS:
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
                            f"[statusline] warning: invalid number for {key}: '{raw_value}'\n"
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
            "compaction_drop_threshold": self.compaction_drop_threshold,
            "compact_mi_warn_threshold": self.compact_mi_warn_threshold,
        }
