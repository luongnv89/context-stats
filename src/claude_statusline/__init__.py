"""Claude Code Context Stats.

Never run out of context unexpectedly - monitor your session context in real-time.
"""

__version__ = "1.6.0"

from claude_statusline.core.config import Config
from claude_statusline.core.state import StateFile

__all__ = ["__version__", "Config", "StateFile"]
