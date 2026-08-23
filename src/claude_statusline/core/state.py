"""State file management for token tracking."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None  # type: ignore[assignment]


def _lock_state_file(fh: object) -> None:
    """Take an exclusive advisory lock on ``fh`` (best-effort, POSIX only).

    Serializes the append + rotation read-modify-write between concurrent
    statusline/CLI processes so rotation cannot drop a concurrently appended
    line (F-BUG-008). No-op on platforms without ``fcntl``.
    """
    if fcntl is None:
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
    except OSError:
        pass  # locking is best-effort; atomic rename still bounds damage


def _unlock_state_file(fh: object) -> None:
    """Release the exclusive lock taken by :func:`_lock_state_file`."""
    if fcntl is None:
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
    except OSError:
        pass


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
    api_duration_ms: int = 0

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
                api_duration_ms=safe_int(parts[14] if len(parts) > 14 else ""),
            )

        except (ValueError, IndexError):
            return None

    def to_csv_line(self) -> str:
        """Convert entry to CSV line.

        Raises:
            ValueError: If ``session_id`` or ``model_id`` contains characters
                that cannot be represented in the unquoted 15-field CSV format
                (commas, newlines, or other control characters).
        """
        _validate_csv_field("session_id", self.session_id)
        _validate_csv_field("model_id", self.model_id)
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
                _sanitize_workspace_dir(self.workspace_project_dir),
                self.context_window_size,
                self.api_duration_ms,
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

    Path-traversal defense plus CSV-safety defense (F-BUG-006): a session_id
    carrying a comma, newline, or other control character would corrupt the
    unquoted 15-field CSV rows (shifting column indexes for index-based
    readers like ``csv_parts[14]``), so those are rejected too.

    Args:
        session_id: Session ID to validate

    Raises:
        ValueError: If session_id is not a str, contains '/', '\\', '..', or
            null bytes, or is not CSV-safe (comma/newline/control chars).
    """
    if not isinstance(session_id, str):
        raise ValueError(f"Invalid session_id: expected str, got {type(session_id).__name__}.")
    for bad in ("/", "\\", "..", "\0"):
        if bad in session_id:
            raise ValueError(
                f"Invalid session_id: contains '{bad}'. "
                "Session IDs must not contain '/', '\\', '..', null bytes, "
                "commas, newlines, or control characters."
            )
    _validate_csv_field("session_id", session_id)


def _csv_unsafe_reason(value: str) -> str | None:
    """Describe why ``value`` cannot be written into an unquoted CSV field.

    Returns ``None`` when the value is safe. The 15-field state format has no
    quoting or escaping, so any comma would shift every following column
    index, and newlines/control characters would corrupt or forge row
    boundaries.
    """
    for i, ch in enumerate(value):
        if ch == ",":
            return f"comma at position {i}"
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            return f"control character U+{code:04X} at position {i}"
    return None


def _validate_csv_field(field: str, value: object) -> None:
    """Validate that a string field is safe to write into a CSV state row.

    Args:
        field: Field name used in error messages (e.g. ``"model_id"``)
        value: Value to validate

    Raises:
        ValueError: If value is not a str, or contains commas, newlines, or
            other control characters (F-BUG-006).
    """
    if not isinstance(value, str):
        raise ValueError(f"Invalid {field}: expected str, got {type(value).__name__}.")
    reason = _csv_unsafe_reason(value)
    if reason is not None:
        raise ValueError(
            f"Invalid {field}: contains {reason}. "
            "String fields must not contain commas, newlines, or control "
            "characters (the state CSV has no quoting/escaping)."
        )


def _sanitize_workspace_dir(value: object) -> str:
    """Sanitize ``workspace_project_dir`` before writing (CSV_FORMAT contract).

    Commas — and, defensively, newlines/other control characters — are
    replaced with underscores so the directory path can never shift the CSV
    column indexes. Non-str values yield an empty string.
    """
    if not isinstance(value, str):
        return ""
    return "".join("_" if (ch == "," or ord(ch) < 0x20 or ord(ch) == 0x7F) else ch for ch in value)


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
                try:
                    if not new_file.exists():
                        shutil.move(str(old_file), str(new_file))
                    else:
                        old_file.unlink()
                except OSError as e:
                    # Migration must never break the refresh that triggered it
                    # (F-BUG-005): warn and leave the file for a later pass.
                    sys.stderr.write(
                        f"[statusline] warning: failed to migrate legacy state "
                        f"file {old_file}: {e}\n"
                    )

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

        # Find most recent state file by modification time. Each stat() is
        # guarded (F-BUG-008 TOCTOU): a state file may be rotated away or
        # deleted by a concurrent process between the glob and the stat.
        latest_path: Path | None = None
        latest_mtime = -1.0
        for f in self.STATE_DIR.glob("statusline.*.state"):
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_path = f
        if latest_path is not None:
            return latest_path

        # Try default state file
        default = self.STATE_DIR / "statusline.state"
        return default if default.exists() else None

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

    def read_tail(self, n: int) -> list[StateEntry]:
        """Read only the last ``n`` parseable entries from the state file.

        This is the bounded counterpart to :meth:`read_history` used by the
        statusline hot path (tok/s rolling average) so that every refresh
        parses at most ``n`` rows instead of the whole file. State files are
        append-only and chronological, so the tail is the most recent history.

        Parity: the result is byte-for-byte identical to ``read_history()[-n:]``
        — blank lines are skipped and unparseable lines are dropped exactly as
        in :meth:`read_history`, the kept entries are in the same chronological
        order, and exactly the last ``n`` *parseable* entries are returned.
        ``read_history`` itself is intentionally left unchanged because the CLI
        graph/export consumers need the full series.

        Args:
            n: Maximum number of most-recent parseable entries to return.
                Values ``<= 0`` yield an empty list.

        Returns:
            Up to ``n`` of the most recent StateEntry objects, oldest first.
        """
        if n <= 0:
            return []

        file_path = self.find_latest_state_file()
        if not file_path or not file_path.exists():
            return []

        try:
            content = file_path.read_text()
        except OSError as e:
            sys.stderr.write(f"[statusline] warning: failed to read state tail {file_path}: {e}\n")
            return []

        # Walk the file from the end, parsing lines until ``n`` parseable
        # entries are collected. Bounding the parse (one StateEntry build per
        # kept line) is the win here: the full read built an entry for every
        # line in the file. Skipping/dropping mirrors read_history exactly, so
        # the tail equals read_history()[-n:].
        entries: list[StateEntry] = []
        for line in reversed(content.splitlines()):
            if not line.strip():
                continue
            entry = StateEntry.from_csv_line(line)
            if entry:
                entries.append(entry)
                if len(entries) >= n:
                    break
        entries.reverse()  # restore chronological (oldest-first) order
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

        The file is created with owner-only permissions (0600) — state rows
        carry session ids and costs, matching the pr-number-cache precedent.

        The append and the subsequent rotation share one exclusive advisory
        lock (POSIX ``fcntl``, best-effort) so a concurrent process cannot
        append between rotation's line-count read and its atomic rename
        (F-BUG-008). Entries whose string fields would corrupt the CSV are
        rejected with a stderr warning instead of being written (F-BUG-006).

        Platforms without ``fcntl`` (Windows) cannot run the locked inline
        rotation either — ``os.replace`` fails while the append descriptor
        holds the target open — so they fall back to the unlocked
        ``_maybe_rotate`` pass once the descriptor is closed.
        """
        try:
            line = entry.to_csv_line()
        except ValueError as e:
            sys.stderr.write(
                f"[statusline] warning: refusing to write state {self.file_path}: {e}\n"
            )
            return
        try:
            fd = os.open(self.file_path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a+") as f:
                _lock_state_file(f)
                try:
                    f.write(f"{line}\n")
                    f.flush()
                    if fcntl is not None:
                        # POSIX only: the rename may run while this descriptor
                        # still holds the file open. Windows cannot replace an
                        # open file, so it falls back after the close below.
                        self._rotate_locked(f)
                finally:
                    _unlock_state_file(f)
        except OSError as e:
            sys.stderr.write(f"[statusline] warning: failed to write state {self.file_path}: {e}\n")
            return
        if fcntl is None:
            self._maybe_rotate()

    def _rotate_locked(self, fh: object) -> None:
        """Rotation core — caller must hold the exclusive lock on ``fh``.

        If the file has more than ROTATION_THRESHOLD lines, truncate to
        the most recent ROTATION_KEEP lines via atomic temp-file + rename.
        """
        file_path = self.file_path
        try:
            fh.seek(0)  # type: ignore[attr-defined]
            lines = fh.readlines()  # type: ignore[attr-defined]
            if len(lines) <= self.ROTATION_THRESHOLD:
                return
            self._rotate_lines(file_path, lines)
        except OSError as e:
            sys.stderr.write(
                f"[statusline] warning: failed to rotate state file {file_path}: {e}\n"
            )

    def _rotate_lines(self, file_path: Path, lines: list[str]) -> None:
        """Atomically truncate ``lines`` to the most recent ROTATION_KEEP lines."""
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

    def _maybe_rotate(self) -> None:
        """Rotate state file if it exceeds the line threshold.

        Standalone entry point (also used by tests): reads the line count
        under a best-effort lock, then closes the handle BEFORE the atomic
        rename. Windows cannot ``os.replace`` a path another handle holds
        open, so keeping the descriptor across the rename here would
        silently skip rotation on that platform.
        """
        file_path = self.file_path
        try:
            if not file_path.exists():
                return
            with open(file_path) as f:
                _lock_state_file(f)
                try:
                    f.seek(0)
                    lines = f.readlines()
                finally:
                    _unlock_state_file(f)
            if len(lines) <= self.ROTATION_THRESHOLD:
                return
            self._rotate_lines(file_path, lines)
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
