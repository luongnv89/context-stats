"""Tests for core data pipeline: CSV state parsing, statistics, and zone thresholds."""

import pytest

from claude_statusline.core.colors import ColorManager
from claude_statusline.core.state import StateEntry
from claude_statusline.graphs.renderer import GraphDimensions, GraphRenderer
from claude_statusline.graphs.statistics import (
    Stats,
    calculate_deltas,
    calculate_stats,
    detect_spike,
)


def _make_entry(**kwargs) -> StateEntry:
    """Factory for StateEntry with sensible defaults."""
    defaults = dict(
        timestamp=1710288000,
        total_input_tokens=75000,
        total_output_tokens=8500,
        current_input_tokens=50000,
        current_output_tokens=5000,
        cache_creation=10000,
        cache_read=20000,
        cost_usd=0.05234,
        lines_added=250,
        lines_removed=45,
        session_id="abc-123-def",
        model_id="claude-opus-4-5",
        workspace_project_dir="/home/user/my-project",
        context_window_size=200000,
    )
    defaults.update(kwargs)
    return StateEntry(**defaults)


def _render_summary_output(entries, deltas=None):
    """Render summary and return buffered output as string."""
    renderer = GraphRenderer(
        colors=ColorManager(enabled=False),
        dimensions=GraphDimensions(
            term_width=120,
            term_height=40,
            graph_width=105,
            graph_height=13,
        ),
    )
    renderer.begin_buffering()
    renderer.render_summary(entries, deltas if deltas is not None else [])
    return renderer.get_buffer()


# ---------------------------------------------------------------------------
# Class 1: CSV Round-Trip
# ---------------------------------------------------------------------------


class TestStateEntryRoundTrip:
    """Tests for StateEntry.from_csv_line and to_csv_line."""

    def test_full_14_field_round_trip(self):
        original = _make_entry()
        csv_line = original.to_csv_line()
        parsed = StateEntry.from_csv_line(csv_line)
        assert parsed is not None
        assert parsed.timestamp == original.timestamp
        assert parsed.total_input_tokens == original.total_input_tokens
        assert parsed.total_output_tokens == original.total_output_tokens
        assert parsed.current_input_tokens == original.current_input_tokens
        assert parsed.current_output_tokens == original.current_output_tokens
        assert parsed.cache_creation == original.cache_creation
        assert parsed.cache_read == original.cache_read
        assert parsed.cost_usd == pytest.approx(original.cost_usd)
        assert parsed.lines_added == original.lines_added
        assert parsed.lines_removed == original.lines_removed
        assert parsed.session_id == original.session_id
        assert parsed.model_id == original.model_id
        assert parsed.workspace_project_dir == original.workspace_project_dir
        assert parsed.context_window_size == original.context_window_size

    def test_old_format_two_fields(self):
        entry = StateEntry.from_csv_line("1710288000,50000")
        assert entry is not None
        assert entry.timestamp == 1710288000
        assert entry.total_input_tokens == 50000
        assert entry.total_output_tokens == 0
        assert entry.current_input_tokens == 0
        assert entry.session_id == ""
        assert entry.context_window_size == 0

    def test_old_format_round_trip_expands(self):
        """Old 2-field format expands to 14 fields on serialize."""
        entry = StateEntry.from_csv_line("1710288000,50000")
        assert entry is not None
        csv_line = entry.to_csv_line()
        parts = csv_line.split(",")
        assert len(parts) == 14

    def test_empty_string_returns_none(self):
        assert StateEntry.from_csv_line("") is None

    def test_single_field_returns_none(self):
        assert StateEntry.from_csv_line("1710288000") is None

    def test_non_numeric_timestamp_returns_none(self):
        assert StateEntry.from_csv_line("abc,50000") is None

    def test_missing_fields_default_to_zero(self):
        """Line with only 5 fields: fields 5-13 default to 0/empty."""
        entry = StateEntry.from_csv_line("1710288000,100,200,300,400")
        assert entry is not None
        assert entry.timestamp == 1710288000
        assert entry.total_input_tokens == 100
        assert entry.total_output_tokens == 200
        assert entry.current_input_tokens == 300
        assert entry.current_output_tokens == 400
        assert entry.cache_creation == 0
        assert entry.cache_read == 0
        assert entry.cost_usd == pytest.approx(0.0)
        assert entry.lines_added == 0
        assert entry.lines_removed == 0
        assert entry.session_id == ""
        assert entry.model_id == ""
        assert entry.workspace_project_dir == ""
        assert entry.context_window_size == 0

    def test_non_numeric_fields_default_safely(self):
        """safe_int returns 0 for non-numeric values."""
        line = "1710288000,abc,200,xyz,400,0,0,0.0,0,0,sess,model,/tmp,0"
        entry = StateEntry.from_csv_line(line)
        assert entry is not None
        assert entry.total_input_tokens == 0  # "abc" -> 0
        assert entry.current_input_tokens == 0  # "xyz" -> 0
        assert entry.total_output_tokens == 200

    def test_comma_in_workspace_path_sanitized(self):
        """Commas in workspace_project_dir become underscores on serialize."""
        entry = _make_entry(workspace_project_dir="/home/user/path,with,commas")
        csv_line = entry.to_csv_line()
        assert "/home/user/path_with_commas" in csv_line
        assert "/home/user/path,with,commas" not in csv_line

    def test_comma_in_path_round_trip_lossy(self):
        """Round-trip is intentionally lossy for paths with commas."""
        entry = _make_entry(workspace_project_dir="/home/user/path,with,commas")
        csv_line = entry.to_csv_line()
        parsed = StateEntry.from_csv_line(csv_line)
        assert parsed is not None
        assert parsed.workspace_project_dir == "/home/user/path_with_commas"

    def test_float_cost_preserved(self):
        entry = _make_entry(cost_usd=0.05234)
        csv_line = entry.to_csv_line()
        parsed = StateEntry.from_csv_line(csv_line)
        assert parsed is not None
        assert parsed.cost_usd == pytest.approx(0.05234)

    def test_zero_values_round_trip(self):
        entry = _make_entry(
            total_input_tokens=0,
            total_output_tokens=0,
            current_input_tokens=0,
            current_output_tokens=0,
            cache_creation=0,
            cache_read=0,
            cost_usd=0.0,
            lines_added=0,
            lines_removed=0,
            session_id="",
            model_id="",
            workspace_project_dir="",
            context_window_size=0,
        )
        csv_line = entry.to_csv_line()
        parsed = StateEntry.from_csv_line(csv_line)
        assert parsed is not None
        assert parsed.total_input_tokens == 0
        assert parsed.session_id == ""
        assert parsed.workspace_project_dir == ""

    def test_whitespace_line_stripped(self):
        entry = StateEntry.from_csv_line("  1710288000,50000  \n")
        assert entry is not None
        assert entry.timestamp == 1710288000

    def test_to_csv_line_no_trailing_newline(self):
        entry = _make_entry()
        csv_line = entry.to_csv_line()
        assert "\n" not in csv_line


# ---------------------------------------------------------------------------
# Class 2: StateEntry Properties
# ---------------------------------------------------------------------------


class TestStateEntryProperties:
    """Tests for StateEntry computed properties."""

    def test_total_tokens(self):
        entry = _make_entry(total_input_tokens=75000, total_output_tokens=8500)
        assert entry.total_tokens == 83500

    def test_current_used_tokens(self):
        entry = _make_entry(
            current_input_tokens=50000, cache_creation=10000, cache_read=20000
        )
        assert entry.current_used_tokens == 80000

    def test_current_used_tokens_all_zero(self):
        entry = _make_entry(
            current_input_tokens=0, cache_creation=0, cache_read=0
        )
        assert entry.current_used_tokens == 0


# ---------------------------------------------------------------------------
# Class 3: calculate_deltas
# ---------------------------------------------------------------------------


class TestCalculateDeltas:
    """Tests for calculate_deltas."""

    def test_empty_list(self):
        assert calculate_deltas([]) == []

    def test_single_value(self):
        assert calculate_deltas([100]) == []

    def test_two_values(self):
        assert calculate_deltas([100, 250]) == [150]

    def test_increasing_sequence(self):
        assert calculate_deltas([100, 200, 350, 600]) == [100, 150, 250]

    def test_negative_delta_clamped_to_zero(self):
        """Session reset: value decreases, delta clamped to 0."""
        assert calculate_deltas([500, 300]) == [0]

    def test_mixed_positive_and_negative(self):
        assert calculate_deltas([100, 300, 200, 400]) == [200, 0, 200]

    def test_constant_values(self):
        assert calculate_deltas([100, 100, 100]) == [0, 0]

    def test_large_negative_delta(self):
        """Full session reset from 1M to 0."""
        assert calculate_deltas([1000000, 0]) == [0]


# ---------------------------------------------------------------------------
# Class 4: calculate_stats
# ---------------------------------------------------------------------------


class TestCalculateStats:
    """Tests for calculate_stats."""

    def test_empty_data(self):
        result = calculate_stats([])
        assert result == Stats(min_val=0, max_val=0, avg_val=0, total=0, count=0)

    def test_single_value(self):
        result = calculate_stats([42])
        assert result == Stats(min_val=42, max_val=42, avg_val=42, total=42, count=1)

    def test_normal_data(self):
        result = calculate_stats([10, 20, 30, 40, 50])
        assert result.min_val == 10
        assert result.max_val == 50
        assert result.avg_val == 30
        assert result.total == 150
        assert result.count == 5

    def test_avg_uses_integer_division(self):
        result = calculate_stats([10, 20])
        assert result.avg_val == 15  # 30 // 2

    def test_all_same_values(self):
        result = calculate_stats([100, 100, 100])
        assert result.min_val == 100
        assert result.max_val == 100
        assert result.avg_val == 100

    def test_includes_zeros(self):
        result = calculate_stats([0, 0, 100])
        assert result.min_val == 0
        assert result.max_val == 100
        assert result.avg_val == 33  # 100 // 3


# ---------------------------------------------------------------------------
# Class 5: detect_spike (boundary-focused, complements test_icons.py)
# ---------------------------------------------------------------------------


class TestDetectSpike:
    """Boundary and edge-case tests for detect_spike."""

    def test_empty_deltas(self):
        assert detect_spike([], 200000) is False

    def test_at_exactly_15_percent_not_spike(self):
        """30000 = exactly 15% of 200000. Strict > means not a spike."""
        assert detect_spike([30000], 200000) is False

    def test_just_above_15_percent_is_spike(self):
        assert detect_spike([30001], 200000) is True

    def test_relative_at_exactly_3x_not_spike(self):
        """300 = exactly 3x avg(100). Strict > means not a spike."""
        # Previous deltas avg = 100, latest = 300 = 3.0x (not > 3x)
        assert detect_spike([100, 100, 100, 100, 300], 200000) is False

    def test_relative_just_above_3x_is_spike(self):
        assert detect_spike([100, 100, 100, 100, 301], 200000) is True

    def test_zero_avg_no_relative_spike(self):
        """avg=0 skips relative check. 100 < 30000 so no absolute spike."""
        assert detect_spike([0, 0, 0, 0, 100], 200000) is False

    def test_zero_context_window_only_relative(self):
        """Absolute check skipped (ctx=0), but 500 > 3*100 triggers relative."""
        assert detect_spike([100, 100, 100, 100, 500], 0) is True

    def test_window_parameter_limits_lookback(self):
        """With window=2, only last 2 previous deltas used for average."""
        # Previous 2 deltas: [100, 100], avg=100, latest=500 > 300
        assert detect_spike([1000, 100, 100, 500], 200000, window=2) is True

    def test_single_delta_below_absolute(self):
        """Single delta with no previous for relative; below 15% threshold."""
        assert detect_spike([1000], 200000) is False

    def test_single_delta_above_absolute(self):
        assert detect_spike([35000], 200000) is True


# ---------------------------------------------------------------------------
# Class 6: Zone Thresholds (via render_summary)
# ---------------------------------------------------------------------------


class TestZoneThresholds:
    """Tests for zone classification in render_summary.

    Zone boundaries (usage_percentage):
        < 40%  → Smart Zone
        < 80%  → Dumb Zone
        >= 80% → Wrap Up Zone

    Math for context_window_size=200000:
        usage% = 100 - (remaining * 100 // 200000)
        remaining = max(0, 200000 - current_used_tokens)
    """

    def test_zero_usage_smart_zone(self):
        entries = [_make_entry(
            current_input_tokens=0, cache_creation=0, cache_read=0,
            context_window_size=200000,
        )]
        output = _render_summary_output(entries)
        assert "SMART ZONE" in output
        assert "DUMB ZONE" not in output
        assert "WRAP UP ZONE" not in output

    def test_usage_39_pct_smart_zone(self):
        # current_used=78000, remaining=122000, remaining%=61, usage%=39
        entries = [_make_entry(
            current_input_tokens=78000, cache_creation=0, cache_read=0,
            context_window_size=200000,
        )]
        output = _render_summary_output(entries)
        assert "SMART ZONE" in output
        assert "DUMB ZONE" not in output

    def test_usage_40_pct_dumb_zone(self):
        # current_used=78001, remaining=121999, remaining%=60, usage%=40
        entries = [_make_entry(
            current_input_tokens=78001, cache_creation=0, cache_read=0,
            context_window_size=200000,
        )]
        output = _render_summary_output(entries)
        assert "DUMB ZONE" in output
        assert "SMART ZONE" not in output
        assert "WRAP UP ZONE" not in output

    def test_usage_79_pct_dumb_zone(self):
        # current_used=158000, remaining=42000, remaining%=21, usage%=79
        entries = [_make_entry(
            current_input_tokens=158000, cache_creation=0, cache_read=0,
            context_window_size=200000,
        )]
        output = _render_summary_output(entries)
        assert "DUMB ZONE" in output
        assert "WRAP UP ZONE" not in output

    def test_usage_80_pct_wrap_up_zone(self):
        # current_used=158001, remaining=41999, remaining%=20, usage%=80
        entries = [_make_entry(
            current_input_tokens=158001, cache_creation=0, cache_read=0,
            context_window_size=200000,
        )]
        output = _render_summary_output(entries)
        assert "WRAP UP ZONE" in output
        assert "DUMB ZONE" not in output

    def test_usage_100_pct_wrap_up_zone(self):
        entries = [_make_entry(
            current_input_tokens=200000, cache_creation=0, cache_read=0,
            context_window_size=200000,
        )]
        output = _render_summary_output(entries)
        assert "WRAP UP ZONE" in output

    def test_usage_exceeds_context_window(self):
        """Remaining clamped to 0 when usage exceeds window."""
        entries = [_make_entry(
            current_input_tokens=250000, cache_creation=0, cache_read=0,
            context_window_size=200000,
        )]
        output = _render_summary_output(entries)
        assert "WRAP UP ZONE" in output

    def test_cache_tokens_contribute_to_usage(self):
        """cache_creation + cache_read push usage past 40% boundary."""
        # current_used = 40000 + 20000 + 18001 = 78001 → usage=40% → Dumb Zone
        entries = [_make_entry(
            current_input_tokens=40000, cache_creation=20000, cache_read=18001,
            context_window_size=200000,
        )]
        output = _render_summary_output(entries)
        assert "DUMB ZONE" in output
        assert "SMART ZONE" not in output

    def test_zero_context_window_no_zone_output(self):
        """No zone displayed when context_window_size is 0."""
        entries = [_make_entry(context_window_size=0)]
        output = _render_summary_output(entries)
        assert "ZONE" not in output

    def test_empty_entries_no_output(self):
        output = _render_summary_output([])
        assert output == ""


# ---------------------------------------------------------------------------
# Class 7: Cache Graph Rendering
# ---------------------------------------------------------------------------


def _render_graphs_output(entries, graph_type):
    """Render graphs and return buffered output as string."""
    renderer = GraphRenderer(
        colors=ColorManager(enabled=False),
        dimensions=GraphDimensions(
            term_width=120,
            term_height=40,
            graph_width=105,
            graph_height=13,
        ),
    )
    renderer.begin_buffering()
    timestamps = [e.timestamp for e in entries]
    cache_creation = [e.cache_creation for e in entries]
    cache_read_tokens = [e.cache_read for e in entries]
    current_input = [e.current_input_tokens for e in entries]
    current_output = [e.current_output_tokens for e in entries]
    context_used = [e.current_used_tokens for e in entries]
    deltas = calculate_deltas(context_used)
    delta_times = timestamps[1:]

    if graph_type in ("cumulative", "both", "all"):
        renderer.render_timeseries(context_used, timestamps, "Context Usage Over Time", "")
    if graph_type in ("delta", "both", "all"):
        renderer.render_timeseries(deltas, delta_times, "Context Growth Per Interaction", "")
    if graph_type in ("io", "all"):
        renderer.render_timeseries(current_input, timestamps, "Input Tokens (per request)", "")
        renderer.render_timeseries(current_output, timestamps, "Output Tokens (per request)", "")
    if graph_type in ("cache", "all"):
        renderer.render_timeseries(
            cache_creation, timestamps, "Cache Creation Tokens (per request)", ""
        )
        renderer.render_timeseries(
            cache_read_tokens, timestamps, "Cache Read Tokens (per request)", ""
        )

    return renderer.get_buffer()


class TestCacheGraphRendering:
    """Tests for cache graph type rendering."""

    def test_cache_graph_renders_with_data(self):
        entries = [
            _make_entry(timestamp=1000, cache_creation=5000, cache_read=10000),
            _make_entry(timestamp=2000, cache_creation=8000, cache_read=15000),
        ]
        output = _render_graphs_output(entries, "cache")
        assert "Cache Creation Tokens (per request)" in output
        assert "Cache Read Tokens (per request)" in output

    def test_cache_graph_renders_with_zero_data(self):
        entries = [
            _make_entry(timestamp=1000, cache_creation=0, cache_read=0),
            _make_entry(timestamp=2000, cache_creation=0, cache_read=0),
        ]
        output = _render_graphs_output(entries, "cache")
        assert "Cache Creation Tokens (per request)" in output
        assert "Cache Read Tokens (per request)" in output

    def test_cache_included_in_all(self):
        entries = [
            _make_entry(timestamp=1000, cache_creation=5000, cache_read=10000),
            _make_entry(timestamp=2000, cache_creation=8000, cache_read=15000),
        ]
        output = _render_graphs_output(entries, "all")
        assert "Cache Creation Tokens (per request)" in output
        assert "Cache Read Tokens (per request)" in output
        assert "Context Usage Over Time" in output
        assert "Input Tokens (per request)" in output

    def test_cache_not_in_io(self):
        entries = [
            _make_entry(timestamp=1000, cache_creation=5000, cache_read=10000),
            _make_entry(timestamp=2000, cache_creation=8000, cache_read=15000),
        ]
        output = _render_graphs_output(entries, "io")
        assert "Cache Creation Tokens" not in output
        assert "Cache Read Tokens" not in output

    def test_summary_shows_cache_when_nonzero(self):
        entries = [_make_entry(cache_creation=5000, cache_read=10000)]
        output = _render_summary_output(entries)
        assert "Cache Creation:" in output
        assert "Cache Read:" in output

    def test_summary_hides_cache_when_zero(self):
        entries = [_make_entry(cache_creation=0, cache_read=0)]
        output = _render_summary_output(entries)
        assert "Cache Creation:" not in output
        assert "Cache Read:" not in output
