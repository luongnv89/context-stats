"""Tests for the tokens-per-second (tok/s) throughput feature.

Covers the shared compute/format helpers (package + standalone), config
parsing for the new keys, and the standalone end-to-end render path that
reads the previous state row to derive the API-time delta.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from claude_statusline.core.config import Config
from claude_statusline.graphs.statistics import compute_tps, format_tps

SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "statusline.py"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


# Load the standalone script as a module so its functions can be unit-tested
# directly (mirrors how the package helpers are imported above).
_spec = importlib.util.spec_from_file_location("statusline_script", SCRIPT_PATH)
statusline_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(statusline_script)


# ---------------------------------------------------------------------------
# compute_tps — the core formula. Parametrized across both implementations so
# the package and standalone copies are verified to stay in sync.
# ---------------------------------------------------------------------------

_IMPLS = pytest.mark.parametrize(
    "fn",
    [compute_tps, statusline_script.compute_tps],
    ids=["package", "standalone"],
)


class TestComputeTps:
    @_IMPLS
    def test_basic_throughput(self, fn):
        # 5000 output tokens over 5000ms - 4000ms = 1000ms = 1.0s -> 5000 tok/s
        assert fn(5000, 5000, 4000) == pytest.approx(5000.0)

    @_IMPLS
    def test_fractional_seconds(self, fn):
        # 250 tokens over 500ms (0.5s) -> 500 tok/s
        assert fn(250, 1500, 1000) == pytest.approx(500.0)

    @_IMPLS
    def test_no_previous_reading_returns_none(self, fn):
        # prev_api_duration == 0 means a legacy/first row: must not compute,
        # otherwise the full cumulative would be treated as one response.
        assert fn(5000, 5000, 0) is None

    @_IMPLS
    def test_negative_previous_returns_none(self, fn):
        assert fn(5000, 5000, -10) is None

    @_IMPLS
    def test_zero_delta_returns_none(self, fn):
        # Same response refreshed twice: api_duration unchanged -> hide.
        assert fn(5000, 5000, 5000) is None

    @_IMPLS
    def test_negative_delta_returns_none(self, fn):
        # api_duration went backwards (shouldn't happen, but guard anyway).
        assert fn(5000, 4000, 5000) is None

    @_IMPLS
    def test_zero_output_returns_none(self, fn):
        assert fn(0, 5000, 4000) is None

    @_IMPLS
    def test_negative_output_returns_none(self, fn):
        assert fn(-100, 5000, 4000) is None


# ---------------------------------------------------------------------------
# format_tps — display formatting
# ---------------------------------------------------------------------------

_FMT_IMPLS = pytest.mark.parametrize(
    "fn",
    [format_tps, statusline_script.format_tps],
    ids=["package", "standalone"],
)


class TestFormatTps:
    @_FMT_IMPLS
    def test_default_precision_and_unit(self, fn):
        assert fn(42.567) == "42.6 tok/s"

    @_FMT_IMPLS
    def test_zero_precision(self, fn):
        assert fn(42.567, precision=0) == "43 tok/s"

    @_FMT_IMPLS
    def test_two_precision(self, fn):
        assert fn(42.567, precision=2) == "42.57 tok/s"

    @_FMT_IMPLS
    def test_custom_unit(self, fn):
        assert fn(42.5, precision=1, unit="tokens/s") == "42.5 tokens/s"

    @_FMT_IMPLS
    def test_negative_precision_clamped(self, fn):
        # Defensive: a negative precision must not raise.
        assert fn(42.5, precision=-2) == "42 tok/s"


# ---------------------------------------------------------------------------
# Config parsing — package Config and standalone read_config
# ---------------------------------------------------------------------------


class TestPackageConfig:
    def test_tps_defaults(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("autocompact=true\n")
        config = Config.load(config_path=config_file)
        assert config.show_tps is False
        assert config.tps_precision == 1
        assert config.tps_unit == "tok/s"

    def test_tps_enabled(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("show_tps=true\ntps_precision=2\ntps_unit=tokens/s\n")
        config = Config.load(config_path=config_file)
        assert config.show_tps is True
        assert config.tps_precision == 2
        assert config.tps_unit == "tokens/s"

    def test_tps_in_to_dict(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("show_tps=true\n")
        d = Config.load(config_path=config_file).to_dict()
        assert d["show_tps"] is True
        assert d["tps_precision"] == 1
        assert d["tps_unit"] == "tok/s"

    def test_invalid_precision_ignored(self, tmp_path, capsys):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("tps_precision=notanumber\n")
        config = Config.load(config_path=config_file)
        assert config.tps_precision == 1  # falls back to default
        assert "tps_precision" in capsys.readouterr().err

    def test_negative_precision_ignored(self, tmp_path, capsys):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("tps_precision=-1\n")
        config = Config.load(config_path=config_file)
        assert config.tps_precision == 1
        assert "tps_precision" in capsys.readouterr().err


class TestStandaloneConfig:
    def _read(self, tmp_path, contents, monkeypatch):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text(contents)
        monkeypatch.setattr(
            os.path, "expanduser", lambda p: str(config_file) if "statusline.conf" in p else p
        )
        return statusline_script.read_config()

    def test_tps_defaults(self, tmp_path, monkeypatch):
        cfg = self._read(tmp_path, "autocompact=true\n", monkeypatch)
        assert cfg["show_tps"] is False
        assert cfg["tps_precision"] == 1
        assert cfg["tps_unit"] == "tok/s"

    def test_tps_enabled(self, tmp_path, monkeypatch):
        cfg = self._read(
            tmp_path, "show_tps=true\ntps_precision=0\ntps_unit=tokens/s\n", monkeypatch
        )
        assert cfg["show_tps"] is True
        assert cfg["tps_precision"] == 0
        assert cfg["tps_unit"] == "tokens/s"


# ---------------------------------------------------------------------------
# Standalone end-to-end: the second invocation should render tok/s using the
# api_duration delta read from the first invocation's persisted state row.
# ---------------------------------------------------------------------------


def _run(input_data: dict, home: Path) -> tuple[str, int]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip(), result.returncode


def _payload(output_tokens: int, api_duration_ms: int, used_input: int) -> dict:
    return {
        "model": {"display_name": "Opus 4.6", "id": "claude-opus-4-6"},
        "workspace": {"current_dir": "/home/user/proj", "project_dir": "/home/user/proj"},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": used_input,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
        "cost": {"total_api_duration_ms": api_duration_ms},
        "session_id": "tps-e2e-session",
    }


class TestStandaloneEndToEnd:
    def test_tps_hidden_on_first_invocation(self, tmp_path):
        """First run has no previous row -> no tok/s, but state is written."""
        conf = tmp_path / ".claude"
        conf.mkdir()
        (conf / "statusline.conf").write_text("show_tps=true\nshow_delta=false\n")

        out, code = _run(_payload(1000, 2000, 10000), tmp_path)
        assert code == 0
        assert "tok/s" not in strip_ansi(out)

        # State row must have been persisted (gate widened for show_tps alone).
        state = conf / "statusline" / "statusline.tps-e2e-session.state"
        assert state.exists()
        row = state.read_text().strip().splitlines()[-1].split(",")
        assert len(row) == 15
        assert row[14] == "2000"  # api_duration_ms persisted

    def test_tps_rendered_on_second_invocation(self, tmp_path):
        """Second run differences api_duration: (5000-2000)ms over 3000 tokens."""
        conf = tmp_path / ".claude"
        conf.mkdir()
        (conf / "statusline.conf").write_text("show_tps=true\nshow_delta=false\n")

        _run(_payload(1000, 2000, 10000), tmp_path)
        # Second response: 3000 output tokens, cumulative api time now 5000ms.
        # delta = 3000ms = 3.0s -> 3000 / 3.0 = 1000.0 tok/s
        out, code = _run(_payload(3000, 5000, 20000), tmp_path)
        assert code == 0
        clean = strip_ansi(out)
        assert "1000.0 tok/s" in clean

    def test_tps_alone_works_without_delta_or_mi(self, tmp_path):
        """show_tps=true with show_delta/show_mi off still reads+writes state."""
        conf = tmp_path / ".claude"
        conf.mkdir()
        (conf / "statusline.conf").write_text(
            "show_tps=true\nshow_delta=false\nshow_mi=false\nshow_session=false\n"
        )
        _run(_payload(1000, 1000, 10000), tmp_path)
        out, code = _run(_payload(500, 1500, 20000), tmp_path)
        assert code == 0
        # 500 tokens / ((1500-1000)/1000)s = 500 / 0.5 = 1000.0 tok/s
        assert "1000.0 tok/s" in strip_ansi(out)

    def test_tps_respects_precision_and_unit_config(self, tmp_path):
        conf = tmp_path / ".claude"
        conf.mkdir()
        (conf / "statusline.conf").write_text(
            "show_tps=true\nshow_delta=false\ntps_precision=2\ntps_unit=tokens/s\n"
        )
        _run(_payload(1000, 1000, 10000), tmp_path)
        out, _ = _run(_payload(333, 2000, 20000), tmp_path)
        # 333 / ((2000-1000)/1000) = 333 / 1.0 = 333.00 tokens/s
        assert "333.00 tokens/s" in strip_ansi(out)

    def test_tps_hidden_when_no_api_duration_field(self, tmp_path):
        """Old CC versions / minimal payloads lack total_api_duration_ms."""
        conf = tmp_path / ".claude"
        conf.mkdir()
        (conf / "statusline.conf").write_text("show_tps=true\nshow_delta=false\n")
        payload = _payload(1000, 0, 10000)
        del payload["cost"]["total_api_duration_ms"]
        payload["cost"]["total_cost_usd"] = 0.01
        _run(payload, tmp_path)
        out, code = _run(payload, tmp_path)
        assert code == 0
        assert "tok/s" not in strip_ansi(out)
