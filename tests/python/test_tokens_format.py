"""Table-driven edge-case tests for formatters/tokens.py
(issue #140, F-TEST-007).

Covers the zero/negative size guard, the autocompact-disabled branch, and the
clamping path in calculate_context_usage, plus abbreviation boundaries in
format_tokens.
"""

from __future__ import annotations

import pytest

from claude_statusline.formatters.tokens import (
    calculate_context_usage,
    format_tokens,
)


class TestFormatTokens:
    @pytest.mark.parametrize(
        "count,expected",
        [
            (0, "0"),
            (1, "1"),
            (42, "42"),
            (999, "999"),
            (1_000, "1,000"),
            (64_000, "64,000"),
            (1_000_000, "1,000,000"),
            (-5_000, "-5,000"),
        ],
    )
    def test_detail_mode_exact_with_commas(self, count, expected):
        assert format_tokens(count, detail=True) == expected

    @pytest.mark.parametrize(
        "count,expected",
        [
            (0, "0"),
            (1, "1"),
            (999, "999"),  # below k boundary stays plain
            (1_000, "1.0k"),  # exact k boundary abbreviates
            (1_500, "1.5k"),
            (999_999, "1000.0k"),  # still below 1M
            (1_000_000, "1.0M"),  # exact M boundary
            (2_500_000, "2.5M"),
            (-5_000, "-5000"),  # negatives fall through to str()
        ],
    )
    def test_abbreviated_mode_boundaries(self, count, expected):
        assert format_tokens(count, detail=False) == expected


class TestCalculateContextUsage:
    @pytest.mark.parametrize("total_size", [0, -200_000])
    def test_non_positive_total_guard(self, total_size):
        """Zero/negative window short-circuits to all-zero stats."""
        assert calculate_context_usage(50_000, total_size) == (0, 0.0, 0)

    def test_autocompact_enabled_default_ratio(self):
        free, pct, buf = calculate_context_usage(100_000, 200_000)
        assert buf == 45_000  # int(200k * 0.225)
        assert free == 55_000
        assert pct == pytest.approx(27.5)

    def test_custom_ratio(self):
        _, _, buf = calculate_context_usage(0, 100_000, autocompact_ratio=0.5)
        assert buf == 50_000

    def test_autocompact_disabled_branch_skips_buffer(self):
        """Disabled autocompact frees the whole remainder — no buffer carve-out."""
        free, pct, buf = calculate_context_usage(100_000, 200_000, autocompact_enabled=False)
        assert buf == 45_000  # buffer still reported…
        assert free == 100_000  # …but not subtracted
        assert pct == pytest.approx(50.0)

    def test_overrun_clamps_free_to_zero(self):
        """used beyond the effective ceiling clamps to 0, never negative."""
        free, pct, _ = calculate_context_usage(300_000, 200_000)
        assert free == 0
        assert pct == 0.0

    def test_disabled_overrun_also_clamps(self):
        free, pct, _ = calculate_context_usage(250_000, 200_000, autocompact_enabled=False)
        assert free == 0
        assert pct == 0.0
