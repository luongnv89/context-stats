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
    """compute_tps takes chronological (output_tokens, cumulative_api_ms)
    samples and returns a rolling, token-weighted tok/s over the last
    ``window`` valid turns. A *turn* is the transition between two samples.
    """

    @_IMPLS
    def test_single_turn(self, fn):
        # One transition: 5000 output over (5000-4000)ms = 1.0s -> 5000 tok/s.
        # First sample's output is irrelevant (it's only the prev duration).
        assert fn([(0, 4000), (5000, 5000)]) == pytest.approx(5000.0)

    @_IMPLS
    def test_fractional_seconds(self, fn):
        # 250 tokens over 500ms (0.5s) -> 500 tok/s
        assert fn([(0, 1000), (250, 1500)]) == pytest.approx(500.0)

    @_IMPLS
    def test_token_weighted_average(self, fn):
        # Two turns: 3000 tok over 37.5s (=80 tok/s) and 3 tok over 2s (=1.5).
        # Mean-of-ratios would be ~40.75; token-weighted is dominated by the
        # substantive turn: 3003 / 39.5s ~= 76.03.
        samples = [(0, 1000), (3000, 38500), (3, 40500)]
        assert fn(samples) == pytest.approx(3003 / 39.5)

    @_IMPLS
    def test_window_limits_turns(self, fn):
        # Four samples -> three valid turns: 10 tok/1s, 10 tok/1s, 1000 tok/1s.
        samples = [(0, 1000), (10, 2000), (10, 3000), (1000, 4000)]
        # window=1 -> just the last turn: 1000 / 1.0 = 1000
        assert fn(samples, 1) == pytest.approx(1000.0)
        # window=3 -> token-weighted over all three: (10+10+1000)/3.0s
        assert fn(samples, 3) == pytest.approx(1020 / 3.0)

    @_IMPLS
    def test_no_previous_reading_returns_none(self, fn):
        # Only one sample -> no turn at all.
        assert fn([(5000, 5000)]) is None

    @_IMPLS
    def test_empty_returns_none(self, fn):
        assert fn([]) is None

    @_IMPLS
    def test_legacy_prev_duration_skipped(self, fn):
        # prev cumulative == 0 means a legacy/first row: that turn is dropped.
        # Here the only turn has prev_dur 0 -> no valid turn -> None.
        assert fn([(0, 0), (5000, 5000)]) is None

    @_IMPLS
    def test_zero_delta_turn_dropped(self, fn):
        # Same response refreshed twice: api_duration unchanged -> turn dropped.
        assert fn([(0, 5000), (5000, 5000)]) is None

    @_IMPLS
    def test_negative_delta_turn_dropped(self, fn):
        # api_duration went backwards (shouldn't happen, but guard anyway).
        assert fn([(0, 5000), (5000, 4000)]) is None

    @_IMPLS
    def test_zero_output_turn_dropped(self, fn):
        assert fn([(0, 4000), (0, 5000)]) is None

    @_IMPLS
    def test_keep_last_average_when_latest_turn_invalid(self, fn):
        # A good turn followed by a zero-output (invalid) turn: the invalid
        # turn is simply not summed, so the prior average persists.
        samples = [(0, 1000), (500, 1500), (0, 2000)]  # turn1 valid, turn2 dropped
        # 500 tok / 0.5s = 1000 tok/s, unaffected by the trailing dud turn.
        assert fn(samples) == pytest.approx(1000.0)

    @_IMPLS
    def test_window_below_one_clamped(self, fn):
        samples = [(0, 1000), (100, 2000)]
        assert fn(samples, 0) == pytest.approx(100.0)


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

    @_FMT_IMPLS
    def test_huge_precision_clamped(self, fn):
        # Defensive: an absurd precision must not emit a megabyte-long field.
        result = fn(42.5, precision=1_000_000)
        assert result == "42.5000000000 tok/s"  # clamped to 10 decimals
        assert len(result) < 30


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
        assert config.tps_window == 5

    def test_tps_enabled(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("show_tps=true\ntps_precision=2\ntps_unit=tokens/s\ntps_window=3\n")
        config = Config.load(config_path=config_file)
        assert config.show_tps is True
        assert config.tps_precision == 2
        assert config.tps_unit == "tokens/s"
        assert config.tps_window == 3

    def test_tps_window_invalid_ignored(self, tmp_path, capsys):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("tps_window=0\n")
        config = Config.load(config_path=config_file)
        assert config.tps_window == 5  # falls back to default
        assert "tps_window" in capsys.readouterr().err

    def test_tps_in_to_dict(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("show_tps=true\n")
        d = Config.load(config_path=config_file).to_dict()
        assert d["show_tps"] is True
        assert d["tps_precision"] == 1
        assert d["tps_unit"] == "tok/s"
        assert d["tps_window"] == 5

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
            tmp_path,
            "show_tps=true\ntps_precision=0\ntps_unit=tokens/s\ntps_window=3\n",
            monkeypatch,
        )
        assert cfg["show_tps"] is True
        assert cfg["tps_precision"] == 0
        assert cfg["tps_unit"] == "tokens/s"
        assert cfg["tps_window"] == 3

    def test_tps_window_default_and_invalid(self, tmp_path, monkeypatch):
        assert self._read(tmp_path, "autocompact=true\n", monkeypatch)["tps_window"] == 5
        # Below-1 and non-integer values are ignored, keeping the default.
        assert self._read(tmp_path, "tps_window=0\n", monkeypatch)["tps_window"] == 5
        assert self._read(tmp_path, "tps_window=nope\n", monkeypatch)["tps_window"] == 5


# ---------------------------------------------------------------------------
# Standalone end-to-end: the second invocation should render tok/s using the
# api_duration delta read from the first invocation's persisted state row.
# ---------------------------------------------------------------------------


def _run(input_data: dict, home: Path) -> tuple[str, int]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["HOME"] = str(home)
    # On Windows, os.path.expanduser("~") resolves via USERPROFILE (then
    # HOMEDRIVE+HOMEPATH), never HOME. Set USERPROFILE too so the temp home
    # redirects the state/config dirs on every platform.
    env["USERPROFILE"] = str(home)
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
        """Second run yields one rolling turn: (5000-2000)ms over 3000 tokens."""
        conf = tmp_path / ".claude"
        conf.mkdir()
        (conf / "statusline.conf").write_text("show_tps=true\nshow_delta=false\n")

        _run(_payload(1000, 2000, 10000), tmp_path)
        # Second response: 3000 output tokens, cumulative api time now 5000ms.
        # One valid turn -> 3000 / ((5000-2000)/1000) = 1000.0 tok/s.
        out, code = _run(_payload(3000, 5000, 20000), tmp_path)
        assert code == 0
        clean = strip_ansi(out)
        assert "1000.0 tok/s" in clean

    def test_tps_rolling_average_smooths_spiky_turns(self, tmp_path):
        """A tiny outlier turn must not crater the rolling token-weighted avg."""
        conf = tmp_path / ".claude"
        conf.mkdir()
        (conf / "statusline.conf").write_text("show_tps=true\nshow_delta=false\ntps_precision=1\n")
        # Turn 1: 3000 tok over (38500-1000)=37.5s  -> 80 tok/s on its own.
        # Turn 2: 3 tok over (40500-38500)=2.0s     -> 1.5 tok/s on its own.
        # Token-weighted rolling avg = 3003 / 39.5s = 76.0 tok/s (not ~40).
        _run(_payload(0, 1000, 10000), tmp_path)
        _run(_payload(3000, 38500, 20000), tmp_path)
        out, code = _run(_payload(3, 40500, 30000), tmp_path)
        assert code == 0
        assert "76.0 tok/s" in strip_ansi(out)

    def test_tps_window_one_uses_only_latest_turn(self, tmp_path):
        """tps_window=1 reduces to the latest turn's instantaneous speed."""
        conf = tmp_path / ".claude"
        conf.mkdir()
        (conf / "statusline.conf").write_text(
            "show_tps=true\nshow_delta=false\ntps_window=1\ntps_precision=1\n"
        )
        _run(_payload(0, 1000, 10000), tmp_path)
        _run(_payload(3000, 38500, 20000), tmp_path)  # 80 tok/s turn
        out, code = _run(_payload(3, 40500, 30000), tmp_path)  # 1.5 tok/s turn
        assert code == 0
        # window=1 -> only the last turn: 3 / 2.0s = 1.5 tok/s.
        assert "1.5 tok/s" in strip_ansi(out)

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
