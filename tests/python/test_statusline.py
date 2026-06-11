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
        assert "%" in output

    def test_ac_not_in_statusline(self, sample_input):
        """AC indicator removed from statusline to save space."""
        output, code = run_script(sample_input)
        assert code == 0
        assert "[AC:" not in output

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
        assert "%" in output

    def test_medium_usage_has_output(self, medium_usage_input):
        """Medium usage (25-50% free) should produce output with 'free'."""
        output, code = run_script(medium_usage_input)
        assert code == 0
        assert "%" in output

    def test_high_usage_has_output(self, high_usage_input):
        """High usage (<25% free) should produce output with 'free'."""
        output, code = run_script(high_usage_input)
        assert code == 0
        assert "%" in output


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
        """Output should fit within 40 columns, preserving dir and context over model."""
        output, code = run_script(sample_input, {"COLUMNS": "40"})
        assert code == 0
        visible = strip_ansi(output)
        assert len(visible) <= 40
        assert "myproject" in visible
        # Model name is lowest priority — truncated first in narrow terminals
        assert "Claude 3.5 Sonnet" not in visible

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


class TestPRDisplay:
    """Tests for PR number display feature (#77)."""

    def test_pr_info_in_parts_order(self, sample_input):
        """PR info should appear after git_info and before context_info in parts."""
        from scripts import statusline as sl

        # Verify the parts list ordering has pr_info between git_info and context_info
        source = sl.__file__
        content = Path(source).read_text(encoding="utf-8")
        # Find the parts = [ ... ] block in main() by searching for the
        # distinctive pattern 'parts = [\n        base,' which is how the statusline builds the parts list.
        parts_start = content.index("parts = [")
        # Find the closing bracket of this list
        parts_block = content[parts_start : parts_start + 2000]
        assert "git_info" in parts_block, "git_info missing from parts list"
        assert "pr_info" in parts_block, "pr_info missing from parts list"
        assert "context_info" in parts_block, "context_info missing from parts list"
        # pr_info must come after git_info and before context_info
        git_idx = parts_block.index("git_info")
        pr_idx = parts_block.index("pr_info")
        ctx_idx = parts_block.index("context_info")
        assert pr_idx > git_idx, "pr_info must come after git_info in parts list"
        assert pr_idx < ctx_idx, "pr_info must come before context_info in parts list"

    def test_show_pr_default_is_false(self, sample_input, tmp_path, monkeypatch):
        """show_pr should default to False — PR hidden without explicit enable."""
        # Create a config file with show_pr=false (default)
        config_file = tmp_path / "statusline.conf"
        config_file.write_text(
            "# default config\nshow_session=true\nshow_pr=false\n",
            encoding="utf-8",
        )
        # Override config path via environment or by patching read_config
        # We use a simpler approach: directly test the Config class
        from claude_statusline.core.config import Config

        cfg = Config.load(str(config_file))
        assert cfg.show_pr is False

    def test_show_pr_true_parsed(self, sample_input, tmp_path, monkeypatch):
        """show_pr=true in config should be parsed correctly."""
        from claude_statusline.core.config import Config

        config_file = tmp_path / "statusline.conf"
        config_file.write_text(
            "show_pr=true\n",
            encoding="utf-8",
        )
        cfg = Config.load(str(config_file))
        assert cfg.show_pr is True

    def test_show_pr_false_parsed(self, sample_input, tmp_path, monkeypatch):
        """show_pr=false in config should be parsed correctly."""
        from claude_statusline.core.config import Config

        config_file = tmp_path / "statusline.conf"
        config_file.write_text(
            "show_pr=false\n",
            encoding="utf-8",
        )
        cfg = Config.load(str(config_file))
        assert cfg.show_pr is False

    def test_show_pr_case_insensitive(self, sample_input, tmp_path, monkeypatch):
        """show_pr value should be case-insensitive."""
        from claude_statusline.core.config import Config

        config_file = tmp_path / "statusline.conf"
        config_file.write_text(
            "show_pr=TRUE\n",
            encoding="utf-8",
        )
        cfg = Config.load(str(config_file))
        assert cfg.show_pr is True

        config_file.write_text(
            "show_pr=False\n",
            encoding="utf-8",
        )
        cfg = Config.load(str(config_file))
        assert cfg.show_pr is False

    def test_get_pr_number_gh_not_installed(self, tmp_path, monkeypatch):
        """_get_pr_number should return empty string when gh CLI is not installed."""
        from claude_statusline.core.git import _get_pr_number

        # Mock shutil.which to return None (gh not found)
        monkeypatch.setattr("shutil.which", lambda x: None if x == "gh" else "/usr/bin/git")
        result = _get_pr_number(tmp_path)
        assert result == ""

    def test_get_pr_number_no_open_pr(self, tmp_path, monkeypatch):
        """_get_pr_number should return empty when no open PR for branch."""
        from claude_statusline.core.git import _get_pr_number

        def mock_which(cmd):
            return "/usr/bin/gh" if cmd == "gh" else "/usr/bin/git"

        def mock_run(cmd, **kwargs):
            # Git commands succeed to get branch
            if "rev-parse" in cmd:
                result = subprocess.CompletedProcess(cmd, 0, stdout="feature-branch\n", stderr="")
                return result
            # gh pr list returns no PRs
            result = subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
            return result

        monkeypatch.setattr("shutil.which", mock_which)
        monkeypatch.setattr("subprocess.run", mock_run)
        result = _get_pr_number(tmp_path)
        assert result == ""

    def test_get_pr_number_with_open_pr(self, tmp_path, monkeypatch):
        """_get_pr_number should return formatted PR number when open PR exists."""
        from claude_statusline.core.git import _get_pr_number

        def mock_which(cmd):
            return "/usr/bin/gh" if cmd == "gh" else "/usr/bin/git"

        def mock_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                result = subprocess.CompletedProcess(cmd, 0, stdout="feature-branch\n", stderr="")
                return result
            # gh returns a JSON array with one PR
            result = subprocess.CompletedProcess(
                cmd, 0, stdout='[{"number": 42}]', stderr=""
            )
            return result

        monkeypatch.setattr("shutil.which", mock_which)
        monkeypatch.setattr("subprocess.run", mock_run)
        result = _get_pr_number(tmp_path)
        assert result == "#42"

    def test_get_pr_number_timeout_graceful(self, tmp_path, monkeypatch):
        """_get_pr_number should return empty string on subprocess timeout."""
        from claude_statusline.core.git import _get_pr_number

        def mock_which(cmd):
            return "/usr/bin/gh" if cmd == "gh" else "/usr/bin/git"

        def mock_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                result = subprocess.CompletedProcess(cmd, 0, stdout="feature-branch\n", stderr="")
                return result
            raise subprocess.TimeoutExpired(cmd, 5)

        monkeypatch.setattr("shutil.which", mock_which)
        monkeypatch.setattr("subprocess.run", mock_run)
        result = _get_pr_number(tmp_path)
        assert result == ""

    def test_get_pr_number_os_error_graceful(self, tmp_path, monkeypatch):
        """_get_pr_number should return empty string on OSError."""
        from claude_statusline.core.git import _get_pr_number

        def mock_which(cmd):
            return "/usr/bin/gh" if cmd == "gh" else "/usr/bin/git"

        def mock_run(cmd, **kwargs):
            raise OSError("Permission denied")

        monkeypatch.setattr("shutil.which", mock_which)
        monkeypatch.setattr("subprocess.run", mock_run)
        result = _get_pr_number(tmp_path)
        assert result == ""

    def test_get_pr_number_invalid_json(self, tmp_path, monkeypatch):
        """_get_pr_number should handle invalid JSON from gh gracefully."""
        from claude_statusline.core.git import _get_pr_number

        def mock_which(cmd):
            return "/usr/bin/gh" if cmd == "gh" else "/usr/bin/git"

        def mock_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                result = subprocess.CompletedProcess(cmd, 0, stdout="feature-branch\n", stderr="")
                return result
            # gh returns invalid JSON
            result = subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")
            return result

        monkeypatch.setattr("shutil.which", mock_which)
        monkeypatch.setattr("subprocess.run", mock_run)
        result = _get_pr_number(tmp_path)
        assert result == ""

    def test_get_pr_number_non_zero_exit(self, tmp_path, monkeypatch):
        """_get_pr_number should return empty when gh exits non-zero."""
        from claude_statusline.core.git import _get_pr_number

        def mock_which(cmd):
            return "/usr/bin/gh" if cmd == "gh" else "/usr/bin/git"

        def mock_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                result = subprocess.CompletedProcess(cmd, 0, stdout="feature-branch\n", stderr="")
                return result
            # gh exits non-zero
            result = subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error")
            return result

        monkeypatch.setattr("shutil.which", mock_which)
        monkeypatch.setattr("subprocess.run", mock_run)
        result = _get_pr_number(tmp_path)
        assert result == ""

    def test_standalone_script_has_show_pr_config(self):
        """Standalone script should include show_pr in its config default dict."""
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        # Check that show_pr is in the config default dict
        assert '"show_pr": False' in content or "'show_pr': False" in content
        # Check show_pr parsing
        assert 'key == "show_pr"' in content or "key == 'show_pr'" in content

    def test_config_has_show_pr_in_to_dict(self, tmp_path):
        """Config.to_dict() should include show_pr key."""
        from claude_statusline.core.config import Config

        cfg = Config.load(str(tmp_path / "nonexistent"))
        d = cfg.to_dict()
        assert "show_pr" in d
        assert d["show_pr"] is False

    def test_minimal_config_fallback_has_show_pr(self):
        """_MINIMAL_CONFIG_FALLBACK should include show_pr setting."""
        from claude_statusline.core.config import _MINIMAL_CONFIG_FALLBACK

        assert "show_pr" in _MINIMAL_CONFIG_FALLBACK

    def test_pr_display_format_in_standalone(self, monkeypatch):
        """Standalone get_pr_number should format PR as #N."""
        from scripts.statusline import get_pr_number

        def mock_which(cmd):
            return "/usr/bin/gh" if cmd == "gh" else "/usr/bin/git"

        def mock_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                result = subprocess.CompletedProcess(cmd, 0, stdout="feature-branch\n", stderr="")
                return result
            result = subprocess.CompletedProcess(
                cmd, 0, stdout='[{"number": 7}]', stderr=""
            )
            return result

        monkeypatch.setattr("shutil.which", mock_which)
        monkeypatch.setattr("subprocess.run", mock_run)
        result = get_pr_number("/tmp")
        assert result == "#7"

    def test_pr_display_format_standalone_no_pr(self, monkeypatch):
        """Standalone get_pr_number should return empty when no gh CLI."""
        from scripts.statusline import get_pr_number

        monkeypatch.setattr("shutil.which", lambda x: None)
        result = get_pr_number("/tmp")
        assert result == ""
