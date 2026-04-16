"""Tests for session-id auto-detection and sessions listing."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from claude_statusline.cli.context_stats import _normalize_argv, run_sessions
from claude_statusline.core.colors import ColorManager
from claude_statusline.core.state import StateEntry, StateFile


class TestNormalizeArgv:
    """Test _normalize_argv with optional session_id."""

    def test_no_args_defaults_to_graph_none(self):
        action, session_id, remaining = _normalize_argv([])
        assert action == "graph"
        assert session_id is None

    def test_action_only_graph(self):
        action, session_id, remaining = _normalize_argv(["graph"])
        assert action == "graph"
        assert session_id is None

    def test_action_only_export(self):
        action, session_id, remaining = _normalize_argv(["export"])
        assert action == "export"
        assert session_id is None

    def test_action_only_sessions(self):
        action, session_id, remaining = _normalize_argv(["sessions"])
        assert action == "sessions"
        assert session_id is None

    def test_action_only_report(self):
        action, session_id, remaining = _normalize_argv(["report"])
        assert action == "report"
        assert session_id is None

    def test_action_only_explain(self):
        action, session_id, remaining = _normalize_argv(["explain"])
        assert action == "explain"
        assert session_id == "-"

    def test_session_id_and_action(self):
        action, session_id, remaining = _normalize_argv(["abc123", "graph"])
        assert action == "graph"
        assert session_id == "abc123"

    def test_session_id_only_defaults_to_graph(self):
        action, session_id, remaining = _normalize_argv(["abc123"])
        assert action == "graph"
        assert session_id == "abc123"

    def test_flags_passed_through(self):
        action, session_id, remaining = _normalize_argv(["graph", "--no-watch", "--type", "mi"])
        assert action == "graph"
        assert session_id is None
        assert "--no-watch" in remaining
        assert "--type" in remaining
        assert "mi" in remaining

    def test_session_and_flags(self):
        action, session_id, remaining = _normalize_argv(["abc123", "graph", "--no-watch"])
        assert action == "graph"
        assert session_id == "abc123"
        assert "--no-watch" in remaining

    def test_no_args_with_flags(self):
        action, session_id, remaining = _normalize_argv(["--no-color"])
        assert action == "graph"
        assert session_id is None
        assert "--no-color" in remaining

    def test_sessions_with_minutes(self):
        action, session_id, remaining = _normalize_argv(["sessions", "--minutes", "30"])
        assert action == "sessions"
        assert session_id is None
        assert "--minutes" in remaining
        assert "30" in remaining

    def test_unknown_action_with_session_id(self):
        with pytest.raises(SystemExit):
            _normalize_argv(["abc123", "unknown-action"])

    def test_cache_warm_without_session(self):
        action, session_id, remaining = _normalize_argv(["cache-warm"])
        assert action == "cache-warm"
        assert session_id is None


class TestRunSessions:
    """Test run_sessions listing."""

    def test_no_sessions_found(self, tmp_path, capsys):
        colors = ColorManager(enabled=False)
        with patch.object(StateFile, "STATE_DIR", tmp_path):
            run_sessions(5, colors)
        output = capsys.readouterr().out
        assert "No sessions found" in output
        assert "5 minute" in output

    def test_lists_recent_sessions(self, tmp_path):
        colors = ColorManager(enabled=False)

        # Create fake state files
        entry = StateEntry(
            timestamp=int(time.time()),
            total_input_tokens=1000,
            total_output_tokens=500,
            current_input_tokens=100,
            current_output_tokens=50,
            cache_creation=200,
            cache_read=300,
            cost_usd=0.01,
            lines_added=10,
            lines_removed=5,
            session_id="test-session-1",
            model_id="claude-opus-4-6",
            workspace_project_dir="/home/user/project",
            context_window_size=200000,
        )

        state_file = tmp_path / "statusline.test-session-1.state"
        state_file.write_text(entry.to_csv_line() + "\n")

        with patch.object(StateFile, "STATE_DIR", tmp_path):
            run_sessions(5, colors)

    def test_filters_old_sessions(self, tmp_path, capsys):
        colors = ColorManager(enabled=False)

        # Create a state file and set its mtime to 10 minutes ago
        entry = StateEntry(
            timestamp=int(time.time()) - 600,
            total_input_tokens=1000,
            total_output_tokens=500,
            current_input_tokens=100,
            current_output_tokens=50,
            cache_creation=200,
            cache_read=300,
            cost_usd=0.01,
            lines_added=10,
            lines_removed=5,
            session_id="old-session",
            model_id="claude-opus-4-6",
            workspace_project_dir="/home/user/project",
            context_window_size=200000,
        )

        state_file = tmp_path / "statusline.old-session.state"
        state_file.write_text(entry.to_csv_line() + "\n")

        import os

        old_time = time.time() - 600
        os.utime(state_file, (old_time, old_time))

        with patch.object(StateFile, "STATE_DIR", tmp_path):
            # With 5-minute window, the 10-minute-old session should not appear
            run_sessions(5, colors)
        output = capsys.readouterr().out
        assert "old-session" not in output
        assert "No sessions found" in output

    def test_sorts_by_most_recent(self, tmp_path, capsys):
        colors = ColorManager(enabled=False)

        now = time.time()
        for i, sid in enumerate(["session-a", "session-b", "session-c"]):
            entry = StateEntry(
                timestamp=int(now),
                total_input_tokens=1000,
                total_output_tokens=500,
                current_input_tokens=100,
                current_output_tokens=50,
                cache_creation=200,
                cache_read=300,
                cost_usd=0.01,
                lines_added=10,
                lines_removed=5,
                session_id=sid,
                model_id="claude-opus-4-6",
                workspace_project_dir="/home/user/project",
                context_window_size=200000,
            )
            state_file = tmp_path / f"statusline.{sid}.state"
            state_file.write_text(entry.to_csv_line() + "\n")
            import os

            # session-c most recent, session-a oldest
            os.utime(state_file, (now - (2 - i) * 30, now - (2 - i) * 30))

        with patch.object(StateFile, "STATE_DIR", tmp_path):
            run_sessions(5, colors)

        output = capsys.readouterr().out
        # session-c should appear before session-a in output
        pos_c = output.find("session-c")
        pos_a = output.find("session-a")
        assert pos_c < pos_a, "Most recent session should appear first"
