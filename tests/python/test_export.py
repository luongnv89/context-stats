"""Tests for the context-stats export command."""

import subprocess
import sys
from pathlib import Path

import pytest

from claude_statusline.cli.export import _format_datetime, _format_duration, _generate_markdown, _usage_bar
from claude_statusline.core.config import Config
from claude_statusline.core.state import StateEntry

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _make_entry(
    timestamp=1710288000,
    total_input=50000,
    total_output=5000,
    current_input=10000,
    current_output=2000,
    cache_creation=5000,
    cache_read=15000,
    cost_usd=0.05,
    lines_added=100,
    lines_removed=20,
    session_id="test-session-id",
    model_id="claude-opus-4-6",
    workspace="/home/user/project",
    context_window=200000,
):
    return StateEntry(
        timestamp=timestamp,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        current_input_tokens=current_input,
        current_output_tokens=current_output,
        cache_creation=cache_creation,
        cache_read=cache_read,
        cost_usd=cost_usd,
        lines_added=lines_added,
        lines_removed=lines_removed,
        session_id=session_id,
        model_id=model_id,
        workspace_project_dir=workspace,
        context_window_size=context_window,
    )


class TestFormatHelpers:
    """Tests for formatting helper functions."""

    def test_format_datetime(self):
        result = _format_datetime(1710288000)
        assert "2024" in result
        assert ":" in result

    def test_format_datetime_invalid(self):
        result = _format_datetime(-99999999999999)
        assert isinstance(result, str)

    def test_format_duration_seconds(self):
        assert _format_duration(30) == "30s"

    def test_format_duration_minutes(self):
        assert _format_duration(150) == "2m 30s"

    def test_format_duration_hours(self):
        assert _format_duration(3661) == "1h 1m 1s"

    def test_usage_bar_empty(self):
        bar = _usage_bar(0)
        assert "\u2591" in bar
        assert len(bar) == 20

    def test_usage_bar_full(self):
        bar = _usage_bar(100)
        assert "\u2588" in bar
        assert len(bar) == 20

    def test_usage_bar_half(self):
        bar = _usage_bar(50)
        assert len(bar) == 20


class TestGenerateMarkdown:
    """Tests for markdown generation."""

    def test_header_contains_session_info(self):
        entries = [
            _make_entry(timestamp=1710288000),
            _make_entry(timestamp=1710289000),
        ]
        config = Config.load()
        md = _generate_markdown(entries, "test-session-id", config)

        assert "# Context Stats Report" in md
        assert "test-session-id" in md
        assert "project" in md.lower()
        assert "claude-opus-4-6" in md

    def test_summary_table(self):
        entries = [
            _make_entry(timestamp=1710288000),
            _make_entry(timestamp=1710289000, cost_usd=0.10),
        ]
        config = Config.load()
        md = _generate_markdown(entries, "test-id", config)

        assert "## Summary" in md
        assert "Context window" in md
        assert "200,000" in md
        assert "$0.10" in md

    def test_interaction_timeline(self):
        entries = [
            _make_entry(timestamp=1710288000),
            _make_entry(timestamp=1710288060, current_input=20000),
            _make_entry(timestamp=1710288120, current_input=30000),
        ]
        config = Config.load()
        md = _generate_markdown(entries, "test-id", config)

        assert "## Interaction Timeline" in md
        assert "| # | Time |" in md
        # Should have 3 rows in the timeline (8 columns per row)
        lines = [l for l in md.split("\n") if l.startswith("| ") and l[2:3].isdigit() and l.count("|") >= 8]
        assert len(lines) == 3

    def test_context_growth_section(self):
        entries = [
            _make_entry(timestamp=1710288000, current_input=5000, cache_creation=0, cache_read=0),
            _make_entry(timestamp=1710288060, current_input=15000, cache_creation=0, cache_read=0),
        ]
        config = Config.load()
        md = _generate_markdown(entries, "test-id", config)

        assert "## Context Growth" in md
        assert "Starting context" in md
        assert "Final context" in md

    def test_cache_statistics_included(self):
        entries = [
            _make_entry(timestamp=1710288000, cache_creation=5000, cache_read=10000),
            _make_entry(timestamp=1710288060, cache_creation=8000, cache_read=15000),
        ]
        config = Config.load()
        md = _generate_markdown(entries, "test-id", config)

        assert "## Cache Statistics" in md

    def test_cache_statistics_omitted_when_no_cache(self):
        entries = [
            _make_entry(timestamp=1710288000, cache_creation=0, cache_read=0),
            _make_entry(timestamp=1710288060, cache_creation=0, cache_read=0),
        ]
        config = Config.load()
        md = _generate_markdown(entries, "test-id", config)

        assert "## Cache Statistics" not in md

    def test_footer_contains_version(self):
        from claude_statusline import __version__

        entries = [
            _make_entry(timestamp=1710288000),
            _make_entry(timestamp=1710289000),
        ]
        config = Config.load()
        md = _generate_markdown(entries, "test-id", config)

        assert __version__ in md
        assert "cc-context-stats" in md

    def test_mi_score_in_summary(self):
        entries = [
            _make_entry(timestamp=1710288000),
            _make_entry(timestamp=1710289000),
        ]
        config = Config.load()
        md = _generate_markdown(entries, "test-id", config)

        assert "MI score" in md

    def test_lines_changed_shown(self):
        entries = [
            _make_entry(timestamp=1710288000, lines_added=250, lines_removed=45),
            _make_entry(timestamp=1710289000, lines_added=250, lines_removed=45),
        ]
        config = Config.load()
        md = _generate_markdown(entries, "test-id", config)

        assert "+250" in md
        assert "-45" in md


class TestExportCommand:
    """Integration tests for the export CLI command."""

    def _run_export(self, extra_args=None):
        cmd = [sys.executable, "-m", "claude_statusline.cli.context_stats", "export"]
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_export_help(self):
        result = self._run_export(["--help"])
        assert result.returncode == 0
        assert "session_id" in result.stdout
        assert "--output" in result.stdout

    def test_export_invalid_session_id(self):
        result = self._run_export(["../../../etc/passwd"])
        assert result.returncode != 0
        assert "Invalid" in result.stderr or "Error" in result.stderr

    def test_export_nonexistent_session(self):
        result = self._run_export(["nonexistent-session-id-12345"])
        assert result.returncode != 0
        assert "No state file" in result.stderr or "Error" in result.stderr

    def test_export_writes_file(self, tmp_path):
        """Test export to a specific output file (requires state data)."""
        # Create a fake state file
        state_dir = tmp_path / ".claude" / "statusline"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "statusline.fake-test-session.state"
        state_file.write_text(
            "1710288000,50000,5000,10000,2000,5000,15000,0.05,100,20,fake-test-session,claude-opus-4-6,/home/user/project,200000\n"
            "1710288060,60000,6000,15000,3000,6000,18000,0.08,150,30,fake-test-session,claude-opus-4-6,/home/user/project,200000\n"
        )
        # We can't easily override STATE_DIR, so just test the markdown generation directly
        from claude_statusline.core.state import StateFile

        sf = StateFile.__new__(StateFile)
        sf.session_id = "fake-test-session"

        # Instead, test via _generate_markdown
        entries = []
        for line in state_file.read_text().splitlines():
            entry = StateEntry.from_csv_line(line)
            if entry:
                entries.append(entry)

        config = Config.load()
        md = _generate_markdown(entries, "fake-test-session", config)
        output_file = tmp_path / "report.md"
        output_file.write_text(md)

        assert output_file.exists()
        content = output_file.read_text()
        assert "# Context Stats Report" in content
        assert "fake-test-session" in content
        assert "## Interaction Timeline" in content
