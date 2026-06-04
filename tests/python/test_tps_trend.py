"""Tests for the throughput (tokens/s) trend graph — issue #72.

Covers:
  * compute_tps_series — the per-turn throughput series used for plotting,
    including the inherited drop rules and value/timestamp index alignment.
  * _filter_entries_by_minutes — time-range (last N minutes) selection anchored
    to the latest entry's timestamp.
  * _render_tps_graph / render_once --type tps — the rendered output: graph
    title, current + average summary lines, the empty/no-data path, and that
    the time window narrows the displayed average.
  * CLI wiring — `tps` is an accepted --type and --minutes parses.
"""

from __future__ import annotations

import re

import pytest

from claude_statusline.cli.context_stats import (
    _build_graph_parser,
    _filter_entries_by_minutes,
    _render_tps_graph,
    render_once,
)
from claude_statusline.core.colors import ColorManager
from claude_statusline.core.config import Config
from claude_statusline.core.state import StateEntry, StateFile
from claude_statusline.graphs.renderer import GraphRenderer
from claude_statusline.graphs.statistics import compute_tps, compute_tps_series

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _entry(output_tokens: int, api_duration_ms: int, *, ts: int) -> StateEntry:
    """Build a StateEntry with the tok/s-relevant fields set.

    output is current_output_tokens (CSV index 4); api time is api_duration_ms
    (CSV index 14) — the same two fields compute_tps consumes.
    """
    return StateEntry(
        timestamp=ts,
        total_input_tokens=0,
        total_output_tokens=0,
        current_input_tokens=0,
        current_output_tokens=output_tokens,
        cache_creation=0,
        cache_read=0,
        cost_usd=0.0,
        lines_added=0,
        lines_removed=0,
        session_id="s",
        model_id="claude-opus-4-6",
        workspace_project_dir="/home/user/proj",
        context_window_size=200000,
        api_duration_ms=api_duration_ms,
    )


# ---------------------------------------------------------------------------
# compute_tps_series — per-turn throughput points for plotting
# ---------------------------------------------------------------------------


class TestComputeTpsSeries:
    def test_single_valid_turn(self):
        # One transition: 5000 output over (5000-4000)ms = 1.0s -> 5000 tok/s.
        # The point's index is that of the LATER sample (index 1).
        assert compute_tps_series([(0, 4000), (5000, 5000)]) == [(1, pytest.approx(5000.0))]

    def test_multiple_turns_values_and_indices(self):
        # Three turns, each over 1s: 10, 20, 30 tok/s, at later-sample indices 1,2,3.
        samples = [(0, 1000), (10, 2000), (20, 3000), (30, 4000)]
        series = compute_tps_series(samples)
        assert [idx for idx, _ in series] == [1, 2, 3]
        assert [pytest.approx(v) for _, v in series] == [10.0, 20.0, 30.0]

    def test_empty_and_single_sample(self):
        assert compute_tps_series([]) == []
        assert compute_tps_series([(5000, 5000)]) == []

    def test_legacy_prev_row_dropped(self):
        # prev cumulative <= 0 means a legacy/first row -> that turn is dropped.
        assert compute_tps_series([(0, 0), (5000, 5000)]) == []

    def test_zero_delta_and_zero_output_turns_dropped(self):
        # zero api-time delta and zero-output turns are omitted (not zeroed).
        assert compute_tps_series([(0, 5000), (5000, 5000)]) == []  # zero delta
        assert compute_tps_series([(0, 4000), (0, 5000)]) == []  # zero output

    def test_dropped_turn_does_not_desync_indices(self):
        # Middle turn is invalid (zero output); the surviving points must keep
        # their true sample indices so the x-axis stays aligned.
        samples = [
            (0, 1000),  # idx 0
            (100, 2000),  # idx 1: valid -> 100/1s = 100
            (0, 3000),  # idx 2: zero output -> DROPPED
            (300, 4000),  # idx 3: valid -> 300/1s = 300
        ]
        series = compute_tps_series(samples)
        assert [idx for idx, _ in series] == [1, 3]
        assert [pytest.approx(v) for _, v in series] == [100.0, 300.0]


# ---------------------------------------------------------------------------
# _filter_entries_by_minutes — time-range selection (AC3)
# ---------------------------------------------------------------------------


class TestFilterByMinutes:
    def test_none_or_zero_returns_all(self):
        entries = [_entry(10, 1000, ts=t) for t in (0, 60, 120)]
        assert _filter_entries_by_minutes(entries, None) == entries
        assert _filter_entries_by_minutes(entries, 0) == entries
        assert _filter_entries_by_minutes(entries, -5) == entries

    def test_window_anchored_to_latest_timestamp(self):
        # Latest ts = 1000s. A 5-minute (300s) window keeps ts >= 700.
        entries = [_entry(10, 1000, ts=t) for t in (0, 600, 700, 900, 1000)]
        kept = _filter_entries_by_minutes(entries, 5)
        assert [e.timestamp for e in kept] == [700, 900, 1000]

    def test_empty_list(self):
        assert _filter_entries_by_minutes([], 5) == []


# ---------------------------------------------------------------------------
# Rendering — _render_tps_graph and render_once --type tps
# ---------------------------------------------------------------------------


def _capture(renderer: GraphRenderer, fn) -> str:
    """Run a renderer-emitting callable with buffering on and return output."""
    renderer.begin_buffering()
    fn()
    return strip_ansi(renderer.get_buffer())


def _renderer() -> GraphRenderer:
    return GraphRenderer(colors=ColorManager(enabled=False), token_detail=True)


class TestRenderTpsGraph:
    def test_renders_title_current_and_average(self):
        renderer = _renderer()
        colors = ColorManager(enabled=False)
        config = Config()
        # Two turns over 1s each: 100 tok/s then 300 tok/s.
        entries = [
            _entry(0, 1000, ts=0),
            _entry(100, 2000, ts=10),
            _entry(300, 3000, ts=20),
        ]
        out = _capture(renderer, lambda: _render_tps_graph(entries, renderer, colors, config))
        assert "Throughput Trend (tokens/s)" in out
        # Current = latest turn = 300 tok/s.
        assert "Current:" in out
        assert "300.0 tok/s" in out
        # Average = token-weighted over the window = (100+300)/2.0s = 200 tok/s.
        assert "Average:" in out
        assert "200.0 tok/s" in out

    def test_no_data_emits_friendly_message(self):
        renderer = _renderer()
        colors = ColorManager(enabled=False)
        config = Config()
        # All-legacy rows (api_duration 0) -> no valid turn at all.
        entries = [_entry(100, 0, ts=0), _entry(200, 0, ts=10)]
        out = _capture(renderer, lambda: _render_tps_graph(entries, renderer, colors, config))
        assert "Throughput Trend (tokens/s)" in out
        assert "No throughput data yet" in out
        # Must not print a current/average for a series that doesn't exist.
        assert "Current:" not in out

    def test_minutes_window_narrows_average(self):
        renderer = _renderer()
        colors = ColorManager(enabled=False)
        config = Config()
        # ts in seconds. Old slow turn far back, recent fast turns near the end.
        # Latest ts = 1000. A 2-minute (120s) window keeps ts >= 880, i.e. only
        # the last two rows -> one fast turn; the old slow turn is excluded.
        entries = [
            _entry(0, 1000, ts=0),
            _entry(10, 2000, ts=10),  # turn: 10/1s = 10 tok/s (old, slow)
            _entry(0, 3000, ts=900),  # carries cumulative forward into window
            _entry(500, 3500, ts=1000),  # turn: 500/0.5s = 1000 tok/s (recent)
        ]
        out_all = _capture(
            renderer, lambda: _render_tps_graph(entries, renderer, colors, config, minutes=None)
        )
        out_win = _capture(
            renderer, lambda: _render_tps_graph(entries, renderer, colors, config, minutes=2)
        )
        # Windowed view advertises the range and yields the fast average only.
        assert "(last 2m)" in out_win
        assert "1000.0 tok/s" in out_win
        # Full view's average is dragged down by the old slow turn, so it is not
        # the pure fast number.
        assert "1000.0 tok/s" not in out_all.split("Average:")[1]

    def test_average_matches_compute_tps_over_window(self):
        # The printed average must equal compute_tps over the displayed samples.
        config = Config()
        entries = [
            _entry(0, 1000, ts=0),
            _entry(700, 2000, ts=10),
            _entry(300, 4000, ts=20),
        ]
        samples = [(e.current_output_tokens, e.api_duration_ms) for e in entries]
        expected = compute_tps(samples, window=len(samples))
        renderer = _renderer()
        out = _capture(
            renderer,
            lambda: _render_tps_graph(entries, renderer, ColorManager(enabled=False), config),
        )
        assert f"{expected:.1f} tok/s" in out


# ---------------------------------------------------------------------------
# render_once integration with a real (monkeypatched) state file
# ---------------------------------------------------------------------------


def _write_state(tmp_path, monkeypatch, entries: list[StateEntry], session="trend-session"):
    monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
    monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
    (tmp_path / "old").mkdir()
    sf = StateFile(session)
    sf.file_path.write_text("".join(e.to_csv_line() + "\n" for e in entries))
    return sf


class TestRenderOnceTps:
    def test_render_once_tps_type(self, tmp_path, monkeypatch):
        entries = [
            _entry(0, 1000, ts=0),
            _entry(100, 2000, ts=10),
            _entry(300, 3000, ts=20),
        ]
        sf = _write_state(tmp_path, monkeypatch, entries)
        renderer = _renderer()
        result = render_once(
            sf, "tps", renderer, ColorManager(enabled=False), watch_mode=True, config=Config()
        )
        assert isinstance(result, str)
        clean = strip_ansi(result)
        assert "Throughput Trend (tokens/s)" in clean
        assert "300.0 tok/s" in clean  # current

    def test_render_once_all_includes_tps(self, tmp_path, monkeypatch):
        entries = [
            _entry(0, 1000, ts=0),
            _entry(100, 2000, ts=10),
            _entry(300, 3000, ts=20),
        ]
        sf = _write_state(tmp_path, monkeypatch, entries)
        renderer = _renderer()
        result = render_once(
            sf, "all", renderer, ColorManager(enabled=False), watch_mode=True, config=Config()
        )
        assert "Throughput Trend (tokens/s)" in strip_ansi(result)

    def test_render_once_minutes_threads_through(self, tmp_path, monkeypatch):
        entries = [
            _entry(0, 1000, ts=0),
            _entry(10, 2000, ts=10),
            _entry(0, 3000, ts=900),
            _entry(500, 3500, ts=1000),
        ]
        sf = _write_state(tmp_path, monkeypatch, entries)
        renderer = _renderer()
        result = render_once(
            sf,
            "tps",
            renderer,
            ColorManager(enabled=False),
            watch_mode=True,
            config=Config(),
            minutes=2,
        )
        clean = strip_ansi(result)
        assert "(last 2m)" in clean
        assert "1000.0 tok/s" in clean


# ---------------------------------------------------------------------------
# CLI argument wiring
# ---------------------------------------------------------------------------


class TestCliWiring:
    def test_tps_is_valid_type(self):
        parser = _build_graph_parser()
        args = parser.parse_args(["--type", "tps"])
        assert args.type == "tps"
        assert args.minutes is None

    def test_minutes_parses(self):
        parser = _build_graph_parser()
        args = parser.parse_args(["--type", "tps", "--minutes", "15"])
        assert args.type == "tps"
        assert args.minutes == 15

    def test_minutes_defaults_none(self):
        parser = _build_graph_parser()
        args = parser.parse_args([])
        assert args.minutes is None
