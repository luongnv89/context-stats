"""Tests for the context-stats explain command."""

import json
import subprocess
import sys
from pathlib import Path

from claude_statusline.core.colors import ColorManager
from claude_statusline.core.config import Config

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


class TestExplainRender:
    """In-process tests for the explain render helpers."""

    def _explain(self, monkeypatch, capsys, data, no_color=True):
        import claude_statusline.cli.explain as explain_mod

        home = Path(self._tmp_home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(Path, "home", lambda: home)
        explain_mod.run_explain(data, no_color=no_color)
        return capsys.readouterr().out

    def setup_method(self):
        import tempfile

        self._tmp_home = tempfile.mkdtemp(prefix="explain-home-")

    def test_run_explain_full_payload(self, monkeypatch, capsys):
        out = self._explain(
            monkeypatch,
            capsys,
            {
                "model": {"display_name": "Opus", "id": "opus-1", "api_name": "opus"},
                "workspace": {"current_dir": "/w", "project_dir": "/p"},
                "context_window": {
                    "context_window_size": 200000,
                    "total_input_tokens": 1000,
                    "total_output_tokens": 500,
                    "used_percentage": 12.5,
                    "remaining_percentage": 87.5,
                },
                "cost": {"total_cost_usd": 0.5},
                "session_id": "s1",
                "version": "2.0",
            },
        )
        assert "Opus" in out
        assert "Workspace" in out
        assert "Context Window" in out
        assert "Cost" in out
        assert "$0.5000" in out
        assert "Session" in out
        assert "Raw JSON" in out
        assert "Extensions" not in out

    def test_run_explain_no_color_suppresses_ansi(self, monkeypatch, capsys):
        out = self._explain(monkeypatch, capsys, {"model": {"display_name": "X"}})
        assert "\x1b[" not in out

    def test_pct_color_tiers(self):
        from claude_statusline.cli.explain import _pct_color

        colors = ColorManager(enabled=False)
        assert _pct_color(colors, 80.0) == colors.green
        assert _pct_color(colors, 30.0) == colors.yellow
        assert _pct_color(colors, 10.0) == colors.red

    def test_fv_formats_float_and_none(self):
        from claude_statusline.cli.explain import _fv

        colors = ColorManager(enabled=False)
        assert "(absent)" in _fv(colors, None)
        assert _fv(colors, 1.25) == "1.2500"
        assert _fv(colors, "abc") == "abc"

    def test_render_context_window_zero_size(self, capsys):
        from claude_statusline.cli.explain import _render_context_window

        config = Config()
        _render_context_window({"context_window": {}}, ColorManager(enabled=False), config)
        out = capsys.readouterr().out
        assert "(absent" in out
        assert "no API call yet" in out

    def test_render_current_usage_autocompact_disabled(self, capsys):
        from claude_statusline.cli.explain import _render_current_usage

        config = Config()
        config.autocompact = False
        cu = {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 2,
        }
        _render_current_usage(cu, 200000, ColorManager(enabled=False), config)
        out = capsys.readouterr().out
        assert "autocompact:" in out
        assert "disabled" in out

    def test_render_current_usage_free_pct_colors(self, capsys):
        from claude_statusline.cli.explain import _render_current_usage

        config = Config()
        config.autocompact = True
        # 95% free -> green tier; exercises free/effective percentage math
        cu = {"input_tokens": 1000}
        _render_current_usage(cu, 200000, ColorManager(enabled=False), config)
        out = capsys.readouterr().out
        assert "free_tokens" in out
        assert "effective_free" in out

    def test_render_cost_absent_returns_early(self, capsys):
        from claude_statusline.cli.explain import _render_cost

        _render_cost({}, ColorManager(enabled=False))
        assert capsys.readouterr().out == ""

    def test_render_cost_null_cost_usd_shows_absent(self, capsys):
        from claude_statusline.cli.explain import _render_cost

        _render_cost({"cost": {"total_duration_ms": 5}}, ColorManager(enabled=False))
        out = capsys.readouterr().out
        assert "(absent)" in out

    def test_render_extensions_plain_string_values(self, capsys):
        from claude_statusline.cli.explain import _render_extensions

        colors = ColorManager(enabled=False)
        _render_extensions({"vim": "INSERT", "agent": "bot", "output_style": "explanatory"}, colors)
        out = capsys.readouterr().out
        assert "vim_mode:" in out
        assert "INSERT" in out
        assert "bot" in out
        assert "explanatory" in out

    def test_render_config_with_overrides(self, capsys):
        from claude_statusline.cli.explain import _render_config

        config = Config()
        config.color_overrides = {"color_context": "\x1b[38;5;46m"}
        _render_config(config, ColorManager(enabled=True))
        out = capsys.readouterr().out
        assert "color_overrides:" in out
        assert "color_context:" in out

    def test_render_config_override_disabled_palette(self, capsys):
        from claude_statusline.cli.explain import _render_config

        config = Config()
        config.color_overrides = {"color_context": "\x1b[38;5;46m"}
        _render_config(config, ColorManager(enabled=False))
        out = capsys.readouterr().out
        assert "(set)" in out
