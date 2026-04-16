"""State file management for token tracking."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StateEntry:
    """A single state file entry."""

    timestamp: int
    total_input_tokens: int
    total_output_tokens: int
    current_input_tokens: int
    current_output_tokens: int
    cache_creation: int
    cache_read: int
    cost_usd: float
    lines_added: int
    lines_removed: int
    session_id: str
    model_id: str
    workspace_project_dir: str
    context_window_size: int

    @classmethod
    def from_csv_line(cls, line: str) -> StateEntry | None:
        """Parse a CSV line into a StateEntry.

        Args:
            line: CSV line with comma-separated values

        Returns:
            StateEntry or None if parsing fails
        """
        parts = line.strip().split(",")

        # Handle old format (timestamp,tokens) and new format (14 fields)
        if len(parts) < 2:
            return None

        try:
            timestamp = int(parts[0])

            # Old format: timestamp,tokens
            if len(parts) == 2:
                tokens = int(parts[1])
                return cls(
                    timestamp=timestamp,
                    total_input_tokens=tokens,
                    total_output_tokens=0,
                    current_input_tokens=0,
                    current_output_tokens=0,
                    cache_creation=0,
                    cache_read=0,
                    cost_usd=0.0,
                    lines_added=0,
                    lines_removed=0,
                    session_id="",
                    model_id="",
                    workspace_project_dir="",
                    context_window_size=0,
                )

            # New format with all fields
            def safe_int(val: str, default: int = 0) -> int:
                try:
                    return int(val) if val else default
                except ValueError:
                    return default

            def safe_float(val: str, default: float = 0.0) -> float:
                try:
                    return float(val) if val else default
                except ValueError:
                    return default

            return cls(
                timestamp=timestamp,
                total_input_tokens=safe_int(parts[1] if len(parts) > 1 else ""),
                total_output_tokens=safe_int(parts[2] if len(parts) > 2 else ""),
                current_input_tokens=safe_int(parts[3] if len(parts) > 3 else ""),
                current_output_tokens=safe_int(parts[4] if len(parts) > 4 else ""),
                cache_creation=safe_int(parts[5] if len(parts) > 5 else ""),
                cache_read=safe_int(parts[6] if len(parts) > 6 else ""),
                cost_usd=safe_float(parts[7] if len(parts) > 7 else ""),
                lines_added=safe_int(parts[8] if len(parts) > 8 else ""),
                lines_removed=safe_int(parts[9] if len(parts) > 9 else ""),
                session_id=parts[10] if len(parts) > 10 else "",
                model_id=parts[11] if len(parts) > 11 else "",
                workspace_project_dir=parts[12] if len(parts) > 12 else "",
                context_window_size=safe_int(parts[13] if len(parts) > 13 else ""),
            )

        except (ValueError, IndexError):
            return None

    def to_csv_line(self) -> str:
        """Convert entry to CSV line."""
        return ",".join(
            str(x)
            for x in [
                self.timestamp,
                self.total_input_tokens,
                self.total_output_tokens,
                self.current_input_tokens,
                self.current_output_tokens,
                self.cache_creation,
                self.cache_read,
                self.cost_usd,
                self.lines_added,
                self.lines_removed,
                self.session_id,
                self.model_id,
                self.workspace_project_dir.replace(",", "_"),
                self.context_window_size,
            ]
        )

    @property
    def total_tokens(self) -> int:
        """Get combined input + output tokens."""
        return self.total_input_tokens + self.total_output_tokens

    @property
    def current_used_tokens(self) -> int:
        """Get current context usage (input + cache)."""
        return self.current_input_tokens + self.cache_creation + self.cache_read


def _validate_session_id(session_id: str) -> None:
    """Validate that a session ID does not contain dangerous path characters.

    Args:
        session_id: Session ID to validate

    Raises:
        ValueError: If session_id contains '/', '\\', '..', or null bytes
    """
    for bad in ("/", "\\", "..", "\0"):
        if bad in session_id:
            raise ValueError(
                f"Invalid session_id: contains '{bad}'. "
                "Session IDs must not contain '/', '\\', '..', or null bytes."
            )


class StateFile:
    """Manage state files for token tracking."""

    STATE_DIR = Path.home() / ".claude" / "statusline"
    OLD_STATE_DIR = Path.home() / ".claude"
    ROTATION_THRESHOLD = 10_000
    ROTATION_KEEP = 5_000

    def __init__(self, session_id: str | None = None) -> None:
        """Initialize state file manager.

        Args:
            session_id: Optional session ID. If not provided, uses latest session.
        """
        if session_id is not None:
            _validate_session_id(session_id)
        self.session_id = session_id
        self._ensure_state_dir()
        self._migrate_old_files()

    def _ensure_state_dir(self) -> None:
        """Create state directory if it doesn't exist."""
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _migrate_old_files(self) -> None:
        """Migrate old state files from ~/.claude/ to ~/.claude/statusline/."""
        for old_file in self.OLD_STATE_DIR.glob("statusline*.state"):
            if old_file.is_file():
                new_file = self.STATE_DIR / old_file.name
                if not new_file.exists():
                    try:
                        shutil.move(str(old_file), str(new_file))
                    except OSError:
                        pass
                else:
                    try:
                        old_file.unlink()
                    except OSError:
                        pass

    @property
    def file_path(self) -> Path:
        """Get the state file path for the current session."""
        if self.session_id:
            return self.STATE_DIR / f"statusline.{self.session_id}.state"
        return self.STATE_DIR / "statusline.state"

    def find_latest_state_file(self) -> Path | None:
        """Find the most recently modified state file.

        Returns:
            Path to the latest state file, or None if no files exist
        """
        if self.session_id:
            file_path = self.STATE_DIR / f"statusline.{self.session_id}.state"
            return file_path if file_path.exists() else None

        # Find most recent state file by modification time
        state_files = list(self.STATE_DIR.glob("statusline.*.state"))
        if not state_files:
            # Try default state file
            default = self.STATE_DIR / "statusline.state"
            return default if default.exists() else None

        return max(state_files, key=lambda f: f.stat().st_mtime)

    def read_history(self) -> list[StateEntry]:
        """Read all entries from the state file.

        Returns:
            List of StateEntry objects
        """
        file_path = self.find_latest_state_file()
        if not file_path or not file_path.exists():
            return []

        entries = []
        try:
            content = file_path.read_text()
            for line in content.splitlines():
                if line.strip():
                    entry = StateEntry.from_csv_line(line)
                    if entry:
                        entries.append(entry)
        except OSError as e:
            sys.stderr.write(
                f"[statusline] warning: failed to read state history {file_path}: {e}\n"
            )

        return entries

    def read_last_entry(self) -> StateEntry | None:
        """Read only the last entry from the state file.

        Returns:
            The last StateEntry or None if file is empty/missing
        """
        # Use file_path for specific session, find_latest for unspecified session
        file_path = self.file_path if self.session_id else self.find_latest_state_file()
        if not file_path or not file_path.exists():
            return None

        try:
            content = file_path.read_text()
            lines = content.splitlines()
            for line in reversed(lines):
                if line.strip():
                    return StateEntry.from_csv_line(line)
        except OSError as e:
            sys.stderr.write(f"[statusline] warning: failed to read last entry {file_path}: {e}\n")

        return None

    def append_entry(self, entry: StateEntry) -> None:
        """Append an entry to the state file.

        Args:
            entry: StateEntry to append
        """
        try:
            with open(self.file_path, "a") as f:
                f.write(f"{entry.to_csv_line()}\n")
        except OSError as e:
            sys.stderr.write(f"[statusline] warning: failed to write state {self.file_path}: {e}\n")
            return
        self._maybe_rotate()

    def _maybe_rotate(self) -> None:
        """Rotate state file if it exceeds the line threshold.

        If the file has more than ROTATION_THRESHOLD lines, truncate to
        the most recent ROTATION_KEEP lines via atomic temp-file + rename.
        """
        file_path = self.file_path
        try:
            if not file_path.exists():
                return
            lines = file_path.read_text().splitlines(keepends=True)
            if len(lines) <= self.ROTATION_THRESHOLD:
                return
            keep = lines[-self.ROTATION_KEEP :]
            fd = tempfile.NamedTemporaryFile(
                dir=str(self.STATE_DIR), delete=False, mode="w", suffix=".tmp"
            )
            try:
                fd.writelines(keep)
                fd.close()
                os.replace(fd.name, str(file_path))
            except BaseException:
                fd.close()
                try:
                    os.unlink(fd.name)
                except OSError:
                    pass
                raise
        except OSError as e:
            sys.stderr.write(
                f"[statusline] warning: failed to rotate state file {file_path}: {e}\n"
            )

    def list_sessions(self) -> list[str]:
        """List all available session IDs.

        Returns:
            List of session ID strings
        """
        sessions = []
        for file_path in self.STATE_DIR.glob("statusline.*.state"):
            name = file_path.stem  # statusline.{session_id}
            if name.startswith("statusline."):
                session_id = name.removeprefix("statusline.")
                if session_id:
                    sessions.append(session_id)
        return sessions
