"""Tests for the context-stats explain command."""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "json"


class TestExplainCommand:
    """Tests for `context-stats explain`."""

    def _run_explain(self, input_data, extra_args=None):
        """Run context-stats explain with JSON input and return stdout."""
        cmd = [sys.executable, "-m", "claude_statusline.cli.context_stats", "explain"]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(
            cmd,
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result

    def test_explain_shows_model(self):
        data = {"model": {"display_name": "Opus 4.5", "id": "claude-opus-4-5"}}
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "Opus 4.5" in result.stdout
        assert "claude-opus-4-5" in result.stdout

    def test_explain_shows_workspace(self):
        data = {
            "workspace": {
                "current_dir": "/home/user/project",
                "project_dir": "/home/user/project",
            }
        }
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "/home/user/project" in result.stdout

    def test_explain_shows_context_window(self):
        data = {
            "context_window": {
                "context_window_size": 200000,
                "current_usage": {
                    "input_tokens": 50000,
                    "cache_creation_input_tokens": 10000,
                    "cache_read_input_tokens": 20000,
                },
            }
        }
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "200,000" in result.stdout
        assert "50,000" in result.stdout
        assert "context_used" in result.stdout

    def test_explain_shows_cost(self):
        data = {
            "cost": {
                "total_cost_usd": 0.1234,
                "total_lines_added": 100,
                "total_lines_removed": 50,
            }
        }
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "$0.1234" in result.stdout

    def test_explain_shows_session(self):
        data = {"session_id": "abc-123", "version": "2.0.0"}
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "abc-123" in result.stdout
        assert "2.0.0" in result.stdout

    def test_explain_shows_absent_fields(self):
        data = {}
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "(absent)" in result.stdout

    def test_explain_shows_raw_json(self):
        data = {"model": {"display_name": "Test"}}
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "Raw JSON" in result.stdout
        assert '"display_name": "Test"' in result.stdout

    def test_explain_shows_config(self):
        data = {}
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "Active Config" in result.stdout

    def test_explain_with_full_fixture(self):
        with open(FIXTURES_DIR / "valid_full.json") as f:
            data = json.load(f)
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "Opus 4.5" in result.stdout
        assert "test-session-123" in result.stdout

    def test_explain_invalid_json_fails(self):
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline.cli.context_stats", "explain"],
            input="not valid json",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1
        assert "invalid JSON" in result.stderr

    def test_explain_shows_derived_free_tokens(self):
        data = {
            "context_window": {
                "context_window_size": 200000,
                "current_usage": {
                    "input_tokens": 50000,
                    "cache_creation_input_tokens": 10000,
                    "cache_read_input_tokens": 20000,
                },
            }
        }
        result = self._run_explain(data)
        assert result.returncode == 0
        # 200000 - (50000+10000+20000) = 120000
        assert "120,000" in result.stdout
        assert "60.0%" in result.stdout

    def test_explain_no_color_flag(self):
        data = {"model": {"display_name": "Test"}}
        result = subprocess.run(
            [sys.executable, "-m", "claude_statusline.cli.context_stats", "explain", "--no-color"],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Test" in result.stdout
        # No ANSI escape codes when --no-color is passed
        assert "\x1b[" not in result.stdout

    def test_explain_shows_vim_mode(self):
        data = {"vim": {"mode": "NORMAL"}}
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "NORMAL" in result.stdout
        assert "Extensions" in result.stdout

    def test_explain_shows_agent(self):
        data = {"agent": {"name": "my-agent"}}
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "my-agent" in result.stdout
        assert "Extensions" in result.stdout

    def test_explain_shows_output_style(self):
        data = {"output_style": {"name": "concise"}}
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "concise" in result.stdout
        assert "Extensions" in result.stdout

    def test_explain_no_extensions_section_when_absent(self):
        data = {"model": {"display_name": "Test"}}
        result = self._run_explain(data)
        assert result.returncode == 0
        assert "Extensions" not in result.stdout
