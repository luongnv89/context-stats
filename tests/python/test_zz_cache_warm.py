"""Tests for the cache-warm subcommand."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Tests that simulate os.fork() behavior are Unix-only — on Windows the
# cmd_cache_warm_on function exits before reaching the fork code path.
unix_only = pytest.mark.skipif(sys.platform == "win32", reason="os.fork not available on Windows")

from claude_statusline.cli.cache_warm import (
    _clear_warm_state,
    _is_process_alive,
    _parse_duration,
    _save_warm_state,
    _warm_state_path,
    cmd_cache_warm_off,
    cmd_cache_warm_on,
    is_cache_warm_active,
    load_warm_state,
    run_cache_warm,
)


@pytest.fixture()
def tmp_dir(monkeypatch):
    """Provide a temp directory that avoids pytest's tmp_path atexit cleanup.

    pytest's tmp_path registers a cleanup_numbered_dir atexit handler that can
    raise KeyboardInterrupt on Windows when pytest-cov terminates the process.
    Using tempfile.mkdtemp() with explicit cleanup sidesteps this entirely.
    """
    d = tempfile.mkdtemp(prefix="test_cache_warm_")
    path = Path(d)
    monkeypatch.setattr("claude_statusline.cli.cache_warm._STATE_DIR", path)
    yield path
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _mock_colors():
    c = SimpleNamespace()
    for attr in ("green", "yellow", "red", "dim", "bold", "reset", "cyan"):
        setattr(c, attr, "")
    return c


# ---------------------------------------------------------------------------
# _parse_duration
# ---------------------------------------------------------------------------

class TestParseDuration:
    def test_minutes(self):
        assert _parse_duration("30m") == 1800

    def test_hours(self):
        assert _parse_duration("1h") == 3600

    def test_seconds_explicit(self):
        assert _parse_duration("90s") == 90

    def test_bare_integer_defaults_to_seconds(self):
        assert _parse_duration("120") == 120

    def test_uppercase(self):
        assert _parse_duration("5M") == 300

    def test_invalid(self):
        with pytest.raises(ValueError):
            _parse_duration("xyz")

    def test_zero(self):
        assert _parse_duration("0m") == 0


# ---------------------------------------------------------------------------
# State persistence helpers
# ---------------------------------------------------------------------------

class TestWarmStatePersistence:
    def test_save_and_load(self, tmp_dir):
        state = {"pid": 12345, "start_time": 1000, "expiry_time": 2000, "interval": 240}
        _save_warm_state("sess1", state)
        loaded = load_warm_state("sess1")
        assert loaded == state

    def test_load_missing_returns_none(self, tmp_dir):
        assert load_warm_state("nonexistent") is None

    def test_clear_removes_file(self, tmp_dir):
        _save_warm_state("sess2", {"pid": 1})
        _clear_warm_state("sess2")
        assert not (tmp_dir / "cache-warm.sess2.json").exists()

    def test_clear_nonexistent_is_noop(self, tmp_dir):
        _clear_warm_state("ghost")  # Should not raise


# ---------------------------------------------------------------------------
# is_cache_warm_active
# ---------------------------------------------------------------------------

class TestIsCacheWarmActive:
    def test_no_state_returns_false(self, tmp_dir):
        active, remaining = is_cache_warm_active("s1")
        assert active is False
        assert remaining == 0

    def test_expired_state_returns_false_and_clears(self, tmp_dir):
        past = int(time.time()) - 100
        _save_warm_state("s2", {"pid": 99999, "expiry_time": past, "interval": 240})
        active, remaining = is_cache_warm_active("s2")
        assert active is False
        assert remaining == 0
        assert not (tmp_dir / "cache-warm.s2.json").exists()

    def test_active_state_with_live_pid(self, tmp_dir):
        future = int(time.time()) + 600
        own_pid = os.getpid()
        _save_warm_state("s3", {"pid": own_pid, "expiry_time": future, "interval": 240})
        active, remaining = is_cache_warm_active("s3")
        assert active is True
        assert remaining > 0

    def test_dead_pid_returns_false_and_clears(self, tmp_dir):
        future = int(time.time()) + 600
        # Use a PID that is almost certainly dead
        _save_warm_state("s4", {"pid": 9999999, "expiry_time": future, "interval": 240})
        with patch("claude_statusline.cli.cache_warm._is_process_alive", return_value=False):
            active, remaining = is_cache_warm_active("s4")
        assert active is False
        assert not (tmp_dir / "cache-warm.s4.json").exists()


# ---------------------------------------------------------------------------
# cmd_cache_warm_on / cmd_cache_warm_off
# ---------------------------------------------------------------------------

class TestCacheWarmOn:
    @unix_only
    def test_starts_heartbeat_and_saves_state(self, tmp_dir, capsys):
        colors = _mock_colors()

        fake_pid = 42000

        with patch("os.fork", return_value=fake_pid, create=True):
            cmd_cache_warm_on("sess", "10m", colors)

        out = capsys.readouterr().out
        assert "activated" in out.lower()

        state = load_warm_state("sess")
        assert state is not None
        assert state["pid"] == fake_pid
        assert state["expiry_time"] > int(time.time())

    @unix_only
    def test_default_duration_is_30m(self, tmp_dir):
        colors = _mock_colors()

        with patch("os.fork", return_value=99, create=True):
            cmd_cache_warm_on("sess", None, colors)

        state = load_warm_state("sess")
        expected_expiry = int(time.time()) + 30 * 60
        # Allow ±5 seconds for test execution time
        assert abs(state["expiry_time"] - expected_expiry) < 5

    def test_invalid_duration_exits(self, tmp_dir):
        colors = _mock_colors()

        with pytest.raises(SystemExit):
            cmd_cache_warm_on("sess", "badval", colors)

    def test_no_fork_platform_exits(self, tmp_dir, monkeypatch, capsys):
        colors = _mock_colors()

        # Simulate a platform without os.fork (e.g. Windows) by hiding the attribute
        monkeypatch.delattr(os, "fork", raising=False)
        with pytest.raises(SystemExit) as exc:
            cmd_cache_warm_on("sess", "10m", colors)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "unix" in err.lower() or "fork" in err.lower()

    @unix_only
    def test_fork_oserror_exits(self, tmp_dir, capsys):
        colors = _mock_colors()

        with patch("os.fork", side_effect=OSError("resource limit"), create=True):
            with pytest.raises(SystemExit) as exc:
                cmd_cache_warm_on("sess", "10m", colors)
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "fork" in err.lower()

    @unix_only
    def test_already_active_refreshes(self, tmp_dir, capsys):
        colors = _mock_colors()
        future = int(time.time()) + 600
        own_pid = os.getpid()
        _save_warm_state("sess", {"pid": own_pid, "expiry_time": future, "interval": 240})

        with patch("os.fork", return_value=55, create=True), \
             patch("os.kill"):  # suppress signal to own pid during off step
            cmd_cache_warm_on("sess", "5m", colors)

        out = capsys.readouterr().out
        assert "already active" in out.lower()

        # After refresh, new state should exist
        state = load_warm_state("sess")
        assert state is not None
        assert state["pid"] == 55


class TestCacheWarmOff:
    def test_stops_active_session(self, tmp_dir, capsys):
        colors = _mock_colors()
        future = int(time.time()) + 600
        _save_warm_state("sess", {"pid": 9999999, "expiry_time": future, "interval": 240})

        with patch("claude_statusline.cli.cache_warm._is_process_alive", return_value=True), \
             patch("os.kill"):
            cmd_cache_warm_off("sess", colors)

        out = capsys.readouterr().out
        assert "stopped" in out.lower()
        assert load_warm_state("sess") is None

    def test_no_active_session_prints_message(self, tmp_dir, capsys):
        colors = _mock_colors()

        cmd_cache_warm_off("sess", colors)
        out = capsys.readouterr().out
        assert "no active" in out.lower()

    def test_silent_suppresses_output(self, tmp_dir, capsys):
        colors = _mock_colors()

        cmd_cache_warm_off("sess", colors, silent=True)
        out = capsys.readouterr().out
        assert out == ""


# ---------------------------------------------------------------------------
# run_cache_warm dispatcher
# ---------------------------------------------------------------------------

class TestRunCacheWarm:
    def test_no_args_shows_usage(self, tmp_dir, capsys):
        colors = _mock_colors()

        with pytest.raises(SystemExit) as exc:
            run_cache_warm("sess", [], colors)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "cache-warm" in out.lower()

    def test_on_dispatches(self, tmp_dir):
        colors = _mock_colors()

        with patch("claude_statusline.cli.cache_warm.cmd_cache_warm_on") as mock_on:
            run_cache_warm("sess", ["on", "15m"], colors)
            mock_on.assert_called_once_with("sess", "15m", colors)

    def test_off_dispatches(self, tmp_dir):
        colors = _mock_colors()

        with patch("claude_statusline.cli.cache_warm.cmd_cache_warm_off") as mock_off:
            run_cache_warm("sess", ["off"], colors)
            mock_off.assert_called_once_with("sess", colors)

    def test_unknown_subcmd_exits(self, tmp_dir):
        colors = _mock_colors()

        with pytest.raises(SystemExit):
            run_cache_warm("sess", ["status"], colors)
