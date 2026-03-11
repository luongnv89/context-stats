"""Tests for activity tier detection."""

import time

from claude_statusline.core.state import StateEntry
from claude_statusline.graphs.statistics import detect_spike
from claude_statusline.ui.icons import (
    ActivityTier,
    get_activity_tier,
    get_tier_label,
)


def _make_entry(
    timestamp: int = 0,
    current_input: int = 1000,
    cache_creation: int = 0,
    cache_read: int = 0,
    context_window_size: int = 200_000,
) -> StateEntry:
    """Helper to create a StateEntry for testing."""
    return StateEntry(
        timestamp=timestamp,
        total_input_tokens=current_input,
        total_output_tokens=0,
        current_input_tokens=current_input,
        current_output_tokens=0,
        cache_creation=cache_creation,
        cache_read=cache_read,
        cost_usd=0.0,
        lines_added=0,
        lines_removed=0,
        session_id="test",
        model_id="test-model",
        workspace_project_dir="/tmp/test",
        context_window_size=context_window_size,
    )


class TestDetectSpike:
    """Tests for spike detection logic."""

    def test_empty_deltas(self):
        assert detect_spike([], 200_000) is False

    def test_no_spike_small_delta(self):
        deltas = [1000, 1200, 1100, 900, 1000]
        assert detect_spike(deltas, 200_000) is False

    def test_spike_absolute_threshold(self):
        """Delta > 15% of context window is a spike."""
        deltas = [1000, 1200, 1100, 900, 35_000]
        assert detect_spike(deltas, 200_000) is True

    def test_spike_relative_threshold(self):
        """Delta > 3x rolling average is a spike."""
        deltas = [100, 100, 100, 100, 500]
        assert detect_spike(deltas, 200_000) is True

    def test_no_spike_when_all_similar(self):
        deltas = [1000, 1000, 1000, 1000, 1000]
        assert detect_spike(deltas, 200_000) is False

    def test_single_delta_no_spike(self):
        """Single delta can't be a relative spike (no average to compare)."""
        deltas = [1000]
        assert detect_spike(deltas, 200_000) is False

    def test_spike_with_zero_context_window(self):
        """Only relative threshold applies when context_window is 0."""
        deltas = [100, 100, 100, 100, 500]
        assert detect_spike(deltas, 0) is True


class TestActivityTier:
    """Tests for activity tier determination."""

    def test_idle_with_no_entries(self):
        assert get_activity_tier([], 200_000) == ActivityTier.IDLE

    def test_idle_with_single_entry(self):
        entry = _make_entry(timestamp=int(time.time()))
        assert get_activity_tier([entry], 200_000) == ActivityTier.IDLE

    def test_idle_when_stale(self):
        """Entries older than 30s should be idle."""
        old_time = int(time.time()) - 60
        entries = [
            _make_entry(timestamp=old_time, current_input=1000),
            _make_entry(timestamp=old_time + 5, current_input=2000),
        ]
        assert get_activity_tier(entries, 200_000) == ActivityTier.IDLE

    def test_low_activity(self):
        """Small delta (<2% of window) = low."""
        now = int(time.time())
        entries = [
            _make_entry(timestamp=now - 5, current_input=1000),
            _make_entry(timestamp=now, current_input=2000),  # delta=1000, 0.5% of 200k
        ]
        assert get_activity_tier(entries, 200_000) == ActivityTier.LOW

    def test_medium_activity(self):
        """Delta 2-5% of window = medium."""
        now = int(time.time())
        entries = [
            _make_entry(timestamp=now - 5, current_input=1000),
            _make_entry(timestamp=now, current_input=7000),  # delta=6000, 3% of 200k
        ]
        assert get_activity_tier(entries, 200_000) == ActivityTier.MEDIUM

    def test_high_activity(self):
        """Delta 5-15% of window = high."""
        now = int(time.time())
        entries = [
            _make_entry(timestamp=now - 5, current_input=1000),
            _make_entry(timestamp=now, current_input=21000),  # delta=20000, 10% of 200k
        ]
        assert get_activity_tier(entries, 200_000) == ActivityTier.HIGH

    def test_spike_activity(self):
        """Delta > 15% of window = spike."""
        now = int(time.time())
        entries = [
            _make_entry(timestamp=now - 5, current_input=1000),
            _make_entry(timestamp=now, current_input=41000),  # delta=40000, 20% of 200k
        ]
        assert get_activity_tier(entries, 200_000) == ActivityTier.SPIKE

    def test_zero_delta_is_idle(self):
        """No token change = idle (even if recent)."""
        now = int(time.time())
        entries = [
            _make_entry(timestamp=now - 5, current_input=1000),
            _make_entry(timestamp=now, current_input=1000),  # delta=0
        ]
        assert get_activity_tier(entries, 200_000) == ActivityTier.IDLE


class TestGetTierLabel:
    """Tests for tier labels."""

    def test_all_tiers_have_labels(self):
        for tier in ActivityTier:
            label = get_tier_label(tier)
            assert len(label) > 0

    def test_idle_label(self):
        assert get_tier_label(ActivityTier.IDLE) == "Idle"

    def test_spike_label(self):
        assert get_tier_label(ActivityTier.SPIKE) == "Spike!"
