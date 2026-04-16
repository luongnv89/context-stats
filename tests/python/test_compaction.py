"""Tests for compaction event detection (#62) and MI quality flagging (#65)."""

from __future__ import annotations

import pytest

from claude_statusline.core.colors import ColorManager
from claude_statusline.core.config import Config
from claude_statusline.core.state import StateEntry
from claude_statusline.graphs.intelligence import calculate_intelligence
from claude_statusline.graphs.renderer import GraphDimensions, GraphRenderer
from claude_statusline.graphs.statistics import detect_compaction_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    current_input: int = 0,
    cache_creation: int = 0,
    cache_read: int = 0,
    context_window_size: int = 200_000,
    model_id: str = "claude-sonnet-4-6",
) -> StateEntry:
    """Factory for StateEntry with sensible defaults."""
    return StateEntry(
        timestamp=1_000_000,
        total_input_tokens=0,
        total_output_tokens=0,
        current_input_tokens=current_input,
        current_output_tokens=0,
        cache_creation=cache_creation,
        cache_read=cache_read,
        cost_usd=0.0,
        lines_added=0,
        lines_removed=0,
        session_id="test-session",
        model_id=model_id,
        workspace_project_dir="/test/project",
        context_window_size=context_window_size,
    )


def _render_summary_with_compaction(
    entries: list,
    compaction_events: list[tuple[int, float]] | None,
    compact_mi_warn_threshold: float = 0.6,
) -> str:
    """Render summary with compaction data and return buffered output."""
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
    renderer.render_summary(
        entries,
        deltas=[],
        compaction_events=compaction_events,
        compact_mi_warn_threshold=compact_mi_warn_threshold,
    )
    return renderer.get_buffer()


# ---------------------------------------------------------------------------
# Class 1: detect_compaction_events
# ---------------------------------------------------------------------------


class TestDetectCompactionEvents:
    """Unit tests for the detect_compaction_events function."""

    def test_empty_list_returns_empty(self):
        """An empty token list produces no events."""
        assert detect_compaction_events([]) == []

    def test_single_value_returns_empty(self):
        """A single-element list cannot have a compaction."""
        assert detect_compaction_events([100_000]) == []

    def test_two_equal_values_no_compaction(self):
        """Identical consecutive values are not compactions."""
        assert detect_compaction_events([50_000, 50_000]) == []

    def test_growing_context_no_compaction(self):
        """Monotonically increasing token counts have no compactions."""
        values = [10_000, 20_000, 40_000, 80_000, 160_000]
        assert detect_compaction_events(values) == []

    def test_greater_than_50pct_drop_detected(self):
        """A drop of exactly > 50% is detected (new < old * 0.5)."""
        # 100k → 49k: 49k < 100k * 0.5 → compaction
        values = [100_000, 49_000]
        events = detect_compaction_events(values)
        assert events == [1]

    def test_exactly_50pct_drop_not_detected(self):
        """A drop of exactly 50% is NOT a compaction (not strictly less than 50%)."""
        # 100k → 50k: 50k == 100k * 0.5 → NOT a compaction
        values = [100_000, 50_000]
        assert detect_compaction_events(values) == []

    def test_slightly_above_50pct_drop_detected(self):
        """A drop just above 50% threshold is detected."""
        # 100k → 49_999: just under the 50k boundary
        values = [100_000, 49_999]
        events = detect_compaction_events(values)
        assert events == [1]

    def test_multiple_compactions(self):
        """Multiple compaction events in a session are all detected."""
        values = [
            100_000,   # index 0: baseline
            120_000,   # index 1: growth
            40_000,    # index 2: first compaction (40k < 120k * 0.5 = 60k)
            60_000,    # index 3: growth
            10_000,    # index 4: second compaction (10k < 60k * 0.5 = 30k)
        ]
        events = detect_compaction_events(values)
        assert 2 in events
        assert 4 in events
        assert len(events) == 2

    def test_zero_previous_value_skipped(self):
        """If previous token count is 0, the comparison is skipped gracefully."""
        values = [0, 50_000]
        assert detect_compaction_events(values) == []

    def test_custom_threshold_60pct(self):
        """Custom threshold of 0.6 requires > 60% drop."""
        # 100k → 41k: 41k < 100k * (1 - 0.6) = 40k → NOT a compaction at 60% threshold
        values = [100_000, 41_000]
        assert detect_compaction_events(values, drop_threshold=0.6) == []

        # 100k → 39k: 39k < 40k → compaction at 60% threshold
        values2 = [100_000, 39_000]
        assert detect_compaction_events(values2, drop_threshold=0.6) == [1]

    def test_custom_threshold_30pct(self):
        """Sensitive threshold of 0.3 catches smaller drops."""
        # 100k → 65k: 65k < 100k * 0.7 = 70k → compaction at 30% threshold
        values = [100_000, 65_000]
        assert detect_compaction_events(values, drop_threshold=0.3) == [1]

        # Same drop at default 50% threshold → not a compaction
        assert detect_compaction_events(values) == []

    def test_returns_correct_indices(self):
        """Returned indices correspond to the position of the post-compaction value."""
        values = [0, 200_000, 300_000, 80_000, 90_000]
        # index 3: 80k < 300k * 0.5 = 150k → compaction
        events = detect_compaction_events(values)
        assert 3 in events

    def test_gradual_decrease_no_compaction(self):
        """A gradual token decrease (e.g., 10% at a time) is not a compaction."""
        values = [100_000, 90_000, 81_000, 72_900]
        assert detect_compaction_events(values) == []


# ---------------------------------------------------------------------------
# Class 2: MI at compaction (issue #65)
# ---------------------------------------------------------------------------


class TestMiAtCompaction:
    """Tests for MI quality assessment at compaction points."""

    def test_low_mi_at_compaction_detected(self):
        """An entry at high context utilization (low MI) gets a warning."""
        # 90% utilization on a 200k context → very low MI
        entry = _make_entry(current_input=180_000, context_window_size=200_000)
        score = calculate_intelligence(entry, 200_000, "claude-sonnet-4-6")
        assert score.mi < 0.6, f"Expected low MI, got {score.mi:.3f}"

    def test_healthy_mi_at_compaction_no_warning(self):
        """An entry at low context utilization (high MI) gets a neutral note."""
        # 20% utilization → healthy MI
        entry = _make_entry(current_input=40_000, context_window_size=200_000)
        score = calculate_intelligence(entry, 200_000, "claude-sonnet-4-6")
        assert score.mi >= 0.6, f"Expected healthy MI, got {score.mi:.3f}"

    def test_mi_threshold_boundary(self):
        """Entries near the 0.6 MI threshold are correctly classified."""
        # Find a utilization that gives MI just below 0.6 for sonnet (beta=1.5)
        # MI = 1 - u^1.5 = 0.6 → u^1.5 = 0.4 → u = 0.4^(2/3) ≈ 0.543
        entry_low = _make_entry(current_input=120_000, context_window_size=200_000)  # 60%
        score_low = calculate_intelligence(entry_low, 200_000, "claude-sonnet-4-6")
        # At 60% (0.6 utilization): MI = 1 - 0.6^1.5 ≈ 1 - 0.465 = 0.535 < 0.6
        assert score_low.mi < 0.6

        entry_high = _make_entry(current_input=60_000, context_window_size=200_000)  # 30%
        score_high = calculate_intelligence(entry_high, 200_000, "claude-sonnet-4-6")
        # At 30% (0.3 utilization): MI = 1 - 0.3^1.5 ≈ 1 - 0.164 = 0.836 > 0.6
        assert score_high.mi > 0.6


# ---------------------------------------------------------------------------
# Class 3: render_summary with compaction info
# ---------------------------------------------------------------------------


class TestRenderSummaryCompaction:
    """Tests for compaction summary display in render_summary."""

    def _entries(self):
        """Create a minimal list of entries for summary rendering."""
        return [
            _make_entry(current_input=100_000, context_window_size=200_000),
            _make_entry(current_input=120_000, context_window_size=200_000),
        ]

    def test_no_compactions_no_compaction_line(self):
        """When compaction_events is None, no compaction line is shown."""
        output = _render_summary_with_compaction(self._entries(), compaction_events=None)
        assert "Compaction" not in output
        assert "compact" not in output.lower()

    def test_no_compactions_empty_list(self):
        """When compaction_events is an empty list, no compaction line is shown."""
        output = _render_summary_with_compaction(self._entries(), compaction_events=[])
        assert "Compaction" not in output

    def test_single_compaction_count_shown(self):
        """When one compaction event exists, count line is shown."""
        events = [(1, 0.45)]  # low MI compaction
        output = _render_summary_with_compaction(self._entries(), compaction_events=events)
        assert "Compactions:" in output
        assert "1" in output

    def test_multiple_compactions_count_shown(self):
        """Multiple compaction events show correct count."""
        events = [(1, 0.45), (3, 0.82)]
        output = _render_summary_with_compaction(self._entries(), compaction_events=events)
        assert "Compactions:" in output
        assert "2" in output

    def test_low_mi_compact_shows_warning(self):
        """A compaction at low MI (<0.6) shows a warning with the MI value."""
        events = [(1, 0.43)]
        output = _render_summary_with_compaction(
            self._entries(), compaction_events=events, compact_mi_warn_threshold=0.6
        )
        assert "0.43" in output
        # Should include warning symbol or relevant text
        assert any(keyword in output for keyword in ["missed", "low MI", "⚠"])

    def test_healthy_mi_compact_shows_confirmation(self):
        """A compaction at healthy MI (>=0.6) shows a confirmation."""
        events = [(1, 0.82)]
        output = _render_summary_with_compaction(
            self._entries(), compaction_events=events, compact_mi_warn_threshold=0.6
        )
        assert "0.82" in output
        assert any(keyword in output for keyword in ["healthy", "complete", "✓"])

    def test_mixed_compactions(self):
        """Mixed compaction quality shows both warning and confirmation."""
        events = [(1, 0.43), (3, 0.82)]
        output = _render_summary_with_compaction(
            self._entries(), compaction_events=events, compact_mi_warn_threshold=0.6
        )
        assert "0.43" in output
        assert "0.82" in output

    def test_custom_mi_warn_threshold(self):
        """Custom MI warn threshold changes classification."""
        # MI 0.65: above default 0.6 → confirmation; below custom 0.7 → warning
        events = [(1, 0.65)]

        # With default threshold (0.6): MI 0.65 >= 0.6 → confirmation
        output_default = _render_summary_with_compaction(
            self._entries(), compaction_events=events, compact_mi_warn_threshold=0.6
        )
        assert any(keyword in output_default for keyword in ["healthy", "complete", "✓"])

        # With custom threshold (0.7): MI 0.65 < 0.7 → warning
        output_custom = _render_summary_with_compaction(
            self._entries(), compaction_events=events, compact_mi_warn_threshold=0.7
        )
        assert any(keyword in output_custom for keyword in ["missed", "low MI", "⚠"])

    def test_at_threshold_boundary(self):
        """MI exactly at threshold is treated as 'not low' (>=)."""
        events = [(1, 0.6)]  # exactly at default threshold
        output = _render_summary_with_compaction(
            self._entries(), compaction_events=events, compact_mi_warn_threshold=0.6
        )
        # 0.6 >= 0.6 → should be confirmation (healthy), not warning
        assert any(keyword in output for keyword in ["healthy", "complete", "✓"])


# ---------------------------------------------------------------------------
# Class 4: Config parsing for new keys
# ---------------------------------------------------------------------------


class TestCompactionConfig:
    """Tests for compaction config key parsing."""

    def test_default_drop_threshold(self):
        """Default compaction_drop_threshold is 0.5."""
        config = Config()
        assert config.compaction_drop_threshold == 0.5

    def test_default_mi_warn_threshold(self):
        """Default compact_mi_warn_threshold is 0.6."""
        config = Config()
        assert config.compact_mi_warn_threshold == 0.6

    def test_to_dict_includes_compaction_keys(self):
        """to_dict includes both new compaction keys."""
        config = Config()
        d = config.to_dict()
        assert "compaction_drop_threshold" in d
        assert "compact_mi_warn_threshold" in d
        assert d["compaction_drop_threshold"] == 0.5
        assert d["compact_mi_warn_threshold"] == 0.6

    def test_parse_valid_drop_threshold(self, tmp_path):
        """Valid compaction_drop_threshold is parsed from config file."""
        conf = tmp_path / "statusline.conf"
        conf.write_text("compaction_drop_threshold=0.4\n")
        config = Config.load(conf)
        assert config.compaction_drop_threshold == pytest.approx(0.4, abs=1e-6)

    def test_parse_valid_mi_warn_threshold(self, tmp_path):
        """Valid compact_mi_warn_threshold is parsed from config file."""
        conf = tmp_path / "statusline.conf"
        conf.write_text("compact_mi_warn_threshold=0.7\n")
        config = Config.load(conf)
        assert config.compact_mi_warn_threshold == pytest.approx(0.7, abs=1e-6)

    def test_invalid_drop_threshold_uses_default(self, tmp_path):
        """Invalid (out-of-range) compaction_drop_threshold falls back to default."""
        conf = tmp_path / "statusline.conf"
        conf.write_text("compaction_drop_threshold=1.5\n")
        config = Config.load(conf)
        assert config.compaction_drop_threshold == 0.5  # default unchanged

    def test_non_numeric_drop_threshold_uses_default(self, tmp_path):
        """Non-numeric compaction_drop_threshold falls back to default."""
        conf = tmp_path / "statusline.conf"
        conf.write_text("compaction_drop_threshold=banana\n")
        config = Config.load(conf)
        assert config.compaction_drop_threshold == 0.5


# ---------------------------------------------------------------------------
# Class 5: render_timeseries with compaction markers (smoke tests)
# ---------------------------------------------------------------------------


class TestRenderTimeseriesCompaction:
    """Smoke tests for compaction marker overlay in render_timeseries."""

    def _make_renderer(self) -> GraphRenderer:
        return GraphRenderer(
            colors=ColorManager(enabled=False),
            dimensions=GraphDimensions(
                term_width=80,
                term_height=30,
                graph_width=60,
                graph_height=10,
            ),
        )

    def test_no_markers_does_not_error(self):
        """Calling render_timeseries without compaction_indices works normally."""
        renderer = self._make_renderer()
        renderer.begin_buffering()
        renderer.render_timeseries(
            [10_000, 20_000, 30_000],
            [1000, 2000, 3000],
            "Test Graph",
            "",
        )
        output = renderer.get_buffer()
        assert "Test Graph" in output

    def test_markers_included_in_output(self):
        """When compaction_indices are given, ▼ marker appears in output."""
        renderer = self._make_renderer()
        renderer.begin_buffering()
        # Values: grows then compacts at index 2
        renderer.render_timeseries(
            [10_000, 20_000, 5_000, 8_000],
            [1000, 2000, 3000, 4000],
            "Test Graph",
            "",
            compaction_indices=[2],
        )
        output = renderer.get_buffer()
        assert "▼" in output

    def test_no_markers_when_indices_empty(self):
        """Empty compaction_indices list produces no markers."""
        renderer = self._make_renderer()
        renderer.begin_buffering()
        renderer.render_timeseries(
            [10_000, 20_000, 30_000],
            [1000, 2000, 3000],
            "Test Graph",
            "",
            compaction_indices=[],
        )
        output = renderer.get_buffer()
        assert "▼" not in output

    def test_out_of_bounds_index_no_crash(self):
        """Out-of-bounds compaction index is silently ignored."""
        renderer = self._make_renderer()
        renderer.begin_buffering()
        renderer.render_timeseries(
            [10_000, 20_000],
            [1000, 2000],
            "Test Graph",
            "",
            compaction_indices=[99],  # way out of bounds
        )
        output = renderer.get_buffer()
        assert "Test Graph" in output
