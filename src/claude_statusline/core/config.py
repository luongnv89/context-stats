"""Configuration management for statusline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Config:
    """Configuration settings for the statusline."""

    autocompact: bool = True
    token_detail: bool = True
    show_delta: bool = True
    show_session: bool = True
    show_io_tokens: bool = True
    reduced_motion: bool = False

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
"""
            )
        except OSError:
            pass  # Ignore errors creating config

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
                value = value.strip().lower()

                if key == "autocompact":
                    self.autocompact = value != "false"
                elif key == "token_detail":
                    self.token_detail = value != "false"
                elif key == "show_delta":
                    self.show_delta = value != "false"
                elif key == "show_session":
                    self.show_session = value != "false"
                elif key == "show_io_tokens":
                    self.show_io_tokens = value != "false"
                elif key == "reduced_motion":
                    self.reduced_motion = value != "false"
        except OSError:
            pass  # Use defaults on read error

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "autocompact": self.autocompact,
            "token_detail": self.token_detail,
            "show_delta": self.show_delta,
            "show_session": self.show_session,
            "show_io_tokens": self.show_io_tokens,
            "reduced_motion": self.reduced_motion,
        }
