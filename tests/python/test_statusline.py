"""Tests for statusline.py script."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "statusline.py"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(s: str) -> str:
    """Strip ANSI escape sequences from a string."""
    return _ANSI_RE.sub("", s)


def run_script(input_data: dict, env_overrides: dict | None = None) -> tuple[str, int]:
    """Run the statusline.py script with the given input.

    Args:
        input_data: JSON-serializable dict to pass as stdin.
        env_overrides: Optional dict of environment variable overrides.

    Returns:
        Tuple of (stdout, return_code)
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip(), result.returncode


class TestStatuslineScript:
    """Tests for the statusline.py script execution."""

    def test_script_exists(self):
        """Script file should exist."""
        assert SCRIPT_PATH.exists()

    def test_script_is_python(self):
        """Script should have Python shebang."""
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/env python3")

    def test_outputs_model_name(self, sample_input):
        """Should output the model name."""
        output, code = run_script(sample_input)
        assert code == 0
        assert "Claude 3.5 Sonnet" in output

    def test_outputs_directory_name(self, sample_input):
        """Should output the directory name."""
        output, code = run_script(sample_input)
        assert code == 0
        assert "myproject" in output

    def test_shows_free_tokens(self, sample_input):
        """Should show free tokens indicator."""
        output, code = run_script(sample_input)
        assert code == 0
        assert "free" in output

    def test_shows_ac_indicator(self, sample_input):
        """Should show autocompact indicator."""
        output, code = run_script(sample_input)
        assert code == 0
        assert "[AC:" in output

    def test_handles_missing_model(self):
        """Should handle missing model gracefully."""
        input_data = {"workspace": {"current_dir": "/tmp/test", "project_dir": "/tmp/test"}}
        output, code = run_script(input_data)
        assert code == 0
        assert "Claude" in output  # Default fallback

    def test_handles_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input="invalid json",
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        assert "Claude" in result.stdout

    def test_handles_empty_input(self):
        """Should handle empty input gracefully."""
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input="",
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0


class TestContextWindowColors:
    """Tests for context window color coding."""

    def test_low_usage_has_output(self, low_usage_input):
        """Low usage (>50% free) should produce output with 'free'."""
        output, code = run_script(low_usage_input)
        assert code == 0
        assert "free" in output

    def test_medium_usage_has_output(self, medium_usage_input):
        """Medium usage (25-50% free) should produce output with 'free'."""
        output, code = run_script(medium_usage_input)
        assert code == 0
        assert "free" in output

    def test_high_usage_has_output(self, high_usage_input):
        """High usage (<25% free) should produce output with 'free'."""
        output, code = run_script(high_usage_input)
        assert code == 0
        assert "free" in output


class TestFixtures:
    """Tests using fixture files."""

    def test_valid_full_fixture(self, valid_full_input):
        """Should handle valid_full.json fixture."""
        output, code = run_script(valid_full_input)
        assert code == 0
        assert "Opus 4.5" in output
        assert "my-project" in output

    def test_valid_minimal_fixture(self, valid_minimal_input):
        """Should handle valid_minimal.json fixture."""
        output, code = run_script(valid_minimal_input)
        assert code == 0
        assert "Claude" in output

    def test_all_fixtures_succeed(self, fixtures_dir):
        """All JSON fixtures should be processed without errors."""
        for fixture_file in fixtures_dir.glob("*.json"):
            with open(fixture_file) as f:
                input_data = json.load(f)
            output, code = run_script(input_data)
            assert code == 0, f"Failed on fixture: {fixture_file.name}"


class TestSessionDisplay:
    """Tests for session_id display feature."""

    def test_shows_session_id_by_default(self, sample_input):
        """Should show session_id by default (show_session=true)."""
        sample_input["session_id"] = "test-session-12345"
        output, code = run_script(sample_input, {"COLUMNS": "200"})
        assert code == 0
        assert "test-session-12345" in output

    def test_handles_missing_session_id(self, sample_input):
        """Should handle missing session_id gracefully."""
        # Ensure no session_id in input
        if "session_id" in sample_input:
            del sample_input["session_id"]
        output, code = run_script(sample_input)
        assert code == 0


class TestWidthTruncation:
    """Tests for width truncation to fit terminal width."""

    def test_output_fits_80_columns(self, sample_input):
        """Output should fit within 80 columns."""
        sample_input["session_id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        output, code = run_script(sample_input, {"COLUMNS": "80"})
        assert code == 0
        visible = strip_ansi(output)
        assert len(visible) <= 80

    def test_output_fits_narrow_terminal(self, sample_input):
        """Output should fit within 40 columns and still show model+dir."""
        output, code = run_script(sample_input, {"COLUMNS": "40"})
        assert code == 0
        visible = strip_ansi(output)
        assert len(visible) <= 40
        assert "Claude 3.5 Sonnet" in visible
        assert "myproject" in visible

    def test_wide_terminal_shows_all(self, sample_input):
        """Wide terminal should show session_id."""
        sample_input["session_id"] = "test-wide-session-uuid"
        output, code = run_script(sample_input, {"COLUMNS": "200"})
        assert code == 0
        assert "test-wide-session-uuid" in output

    def test_full_input_truncated(self, valid_full_input):
        """Full input with all features should fit within 80 columns."""
        output, code = run_script(valid_full_input, {"COLUMNS": "80"})
        assert code == 0
        visible = strip_ansi(output)
        assert len(visible) <= 80
