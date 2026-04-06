"""Tests for state file rotation and session ID validation."""

import re
import subprocess
import sys

import pytest

from claude_statusline.core.state import StateFile, _validate_session_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_csv_line(index: int) -> str:
    """Generate a deterministic CSV state line for a given index."""
    return (
        f"{1710288000 + index},100,200,300,400,500,600,0.01,"
        f"10,5,sess-{index},model,/tmp/proj,200000"
    )


# ---------------------------------------------------------------------------
# State File Rotation
# ---------------------------------------------------------------------------


class TestStateFileRotation:
    """Tests for _maybe_rotate() in StateFile."""

    def test_below_threshold_no_rotation(self, tmp_path, monkeypatch):
        """File with fewer than 10,000 lines is not rotated."""
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        sf = StateFile("test-session")
        # Write 9,999 lines
        lines = [_make_csv_line(i) + "\n" for i in range(9_999)]
        sf.file_path.write_text("".join(lines))

        sf._maybe_rotate()

        result_lines = sf.file_path.read_text().splitlines()
        assert len(result_lines) == 9_999

    def test_at_threshold_no_rotation(self, tmp_path, monkeypatch):
        """File with exactly 10,000 lines is not rotated."""
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        sf = StateFile("test-session")
        lines = [_make_csv_line(i) + "\n" for i in range(10_000)]
        sf.file_path.write_text("".join(lines))

        sf._maybe_rotate()

        result_lines = sf.file_path.read_text().splitlines()
        assert len(result_lines) == 10_000

    def test_exceeds_threshold_truncates_to_5000(self, tmp_path, monkeypatch):
        """File with 10,001 lines is truncated to 5,000."""
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        sf = StateFile("test-session")
        lines = [_make_csv_line(i) + "\n" for i in range(10_001)]
        sf.file_path.write_text("".join(lines))

        sf._maybe_rotate()

        result_lines = sf.file_path.read_text().splitlines()
        assert len(result_lines) == 5_000

    def test_retained_lines_are_most_recent(self, tmp_path, monkeypatch):
        """After rotation, the retained lines are the last 5,000 of the original."""
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        sf = StateFile("test-session")
        total = 10_001
        lines = [_make_csv_line(i) + "\n" for i in range(total)]
        sf.file_path.write_text("".join(lines))

        sf._maybe_rotate()

        result_lines = sf.file_path.read_text().splitlines()
        # First retained line should be the one at index (total - 5000) = 5001
        assert f"sess-{total - 5000}" in result_lines[0]
        # Last retained line should be the last original line
        assert f"sess-{total - 1}" in result_lines[-1]

    def test_rotation_via_append_entry(self, tmp_path, monkeypatch):
        """append_entry triggers rotation when threshold is exceeded."""
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        sf = StateFile("test-session")
        # Write exactly 10,000 lines (at threshold, no rotation yet)
        lines = [_make_csv_line(i) + "\n" for i in range(10_000)]
        sf.file_path.write_text("".join(lines))

        # Import StateEntry to create a valid entry
        from claude_statusline.core.state import StateEntry

        entry = StateEntry(
            timestamp=1710298000,
            total_input_tokens=100,
            total_output_tokens=200,
            current_input_tokens=300,
            current_output_tokens=400,
            cache_creation=500,
            cache_read=600,
            cost_usd=0.01,
            lines_added=10,
            lines_removed=5,
            session_id="test-session",
            model_id="model",
            workspace_project_dir="/tmp/proj",
            context_window_size=200000,
        )
        sf.append_entry(entry)

        # Now file had 10,001 lines -> should have been rotated to 5,000
        result_lines = sf.file_path.read_text().splitlines()
        assert len(result_lines) == 5_000

    def test_no_temp_files_left_after_rotation(self, tmp_path, monkeypatch):
        """No .tmp files remain after successful rotation."""
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        sf = StateFile("test-session")
        lines = [_make_csv_line(i) + "\n" for i in range(10_001)]
        sf.file_path.write_text("".join(lines))

        sf._maybe_rotate()

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


# ---------------------------------------------------------------------------
# Session ID Validation
# ---------------------------------------------------------------------------


class TestSessionIdValidation:
    """Tests for _validate_session_id and StateFile constructor validation."""

    def test_reject_forward_slash(self):
        with pytest.raises(ValueError, match="/"):
            _validate_session_id("../../etc/passwd")

    def test_reject_backslash(self):
        with pytest.raises(ValueError, match=re.escape("\\")):
            _validate_session_id("..\\..\\etc\\passwd")

    def test_reject_dot_dot(self):
        with pytest.raises(ValueError, match=r"\.\."):
            _validate_session_id("..hidden")

    def test_reject_null_byte(self):
        with pytest.raises(ValueError):
            _validate_session_id("session\0id")

    def test_accept_valid_uuid(self):
        _validate_session_id("abc-123-def-456")  # Should not raise

    def test_accept_hyphens_underscores(self):
        _validate_session_id("my_session-id_123")  # Should not raise

    def test_accept_alphanumeric(self):
        _validate_session_id("abcdef1234567890")  # Should not raise

    def test_statefile_rejects_invalid_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        with pytest.raises(ValueError):
            StateFile("../../etc/passwd")

    def test_statefile_accepts_none_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        sf = StateFile(None)  # Should not raise
        assert sf.session_id is None

    def test_statefile_accepts_valid_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        sf = StateFile("valid-session-123")  # Should not raise
        assert sf.session_id == "valid-session-123"


# ---------------------------------------------------------------------------
# CLI Session ID Rejection (subprocess test)
# ---------------------------------------------------------------------------


class TestCliSessionIdRejection:
    """Test that context-stats CLI rejects invalid session IDs."""

    def test_cli_rejects_path_traversal(self):
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline.cli.context_stats", "../../etc/passwd", "graph"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Invalid session_id" in result.stderr

    def test_cli_rejects_backslash(self):
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline.cli.context_stats", "test\\bad", "graph"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "Invalid session_id" in result.stderr
