"""Tests for layout helpers (visible_width, get_terminal_width, fit_to_width)."""

from unittest.mock import patch

from claude_statusline.formatters.layout import (
    fit_to_width,
    get_terminal_width,
    visible_width,
)


class TestVisibleWidth:
    """Tests for visible_width()."""

    def test_plain_text(self):
        assert visible_width("hello") == 5

    def test_ansi_colored_string(self):
        s = "\033[0;32mgreen\033[0m"
        assert visible_width(s) == 5

    def test_multiple_ansi_codes(self):
        s = "\033[2m[\033[0m\033[0;34mdir\033[0m"
        assert visible_width(s) == 4  # [dir

    def test_empty_string(self):
        assert visible_width("") == 0

    def test_unicode_icons(self):
        assert visible_width("\u25cb") == 1  # ○
        assert visible_width("\u26a1") == 1  # ⚡

    def test_ansi_with_semicolons(self):
        s = "\033[1;31;42mtext\033[0m"
        assert visible_width(s) == 4


class TestGetTerminalWidth:
    """Tests for get_terminal_width()."""

    def test_fallback_to_200_when_no_columns_env(self):
        """When COLUMNS is not set and shutil returns 80, use 200 (Claude Code subprocess)."""
        with (
            patch("claude_statusline.formatters.layout.shutil.get_terminal_size") as mock,
            patch.dict("os.environ", {}, clear=False),
        ):
            # Remove COLUMNS if present
            import os

            os.environ.pop("COLUMNS", None)
            mock.return_value = type("Size", (), {"columns": 80})()
            assert get_terminal_width() == 200

    def test_respects_columns_env_80(self):
        """When COLUMNS=80 is explicitly set, trust it."""
        with (
            patch("claude_statusline.formatters.layout.shutil.get_terminal_size") as mock,
            patch.dict("os.environ", {"COLUMNS": "80"}),
        ):
            mock.return_value = type("Size", (), {"columns": 80})()
            assert get_terminal_width() == 80

    def test_custom_width(self):
        with patch("claude_statusline.formatters.layout.shutil.get_terminal_size") as mock:
            mock.return_value = type("Size", (), {"columns": 120})()
            assert get_terminal_width() == 120


class TestFitToWidth:
    """Tests for fit_to_width()."""

    def test_all_parts_fit(self):
        parts = ["base", " | git", " | ctx"]
        result = fit_to_width(parts, 80)
        assert result == "base | git | ctx"

    def test_drops_lowest_priority(self):
        parts = ["base", " | git", " | ctx", " session-uuid-here"]
        result = fit_to_width(parts, 25)
        assert "base" in result
        assert "session-uuid-here" not in result

    def test_base_always_included(self):
        parts = ["very-long-base-string-that-exceeds-width"]
        result = fit_to_width(parts, 10)
        assert result == "very-long-base-string-that-exceeds-width"

    def test_empty_parts_skipped(self):
        parts = ["base", "", " | ctx", "", " session"]
        result = fit_to_width(parts, 30)
        assert result == "base | ctx session"

    def test_exact_boundary(self):
        parts = ["12345", "67890"]
        result = fit_to_width(parts, 10)
        assert result == "1234567890"

    def test_one_char_over_boundary(self):
        parts = ["12345", "678901"]
        result = fit_to_width(parts, 10)
        assert result == "12345"

    def test_empty_parts_list(self):
        assert fit_to_width([], 80) == ""

    def test_realistic_ansi_strings(self):
        base = "\033[2m[Claude]\033[0m \033[0;34mdir\033[0m"
        git = " | \033[0;35mmain\033[0m"
        ctx = " | \033[0;32m150.0k free (75.0%)\033[0m"
        session = " \033[2mtest-session-uuid-1234\033[0m"

        # base=[Claude] dir = 12, git= | main = 7, ctx= | 150.0k free (75.0%) = 22,
        # session= test-session-uuid-1234 = 23 => total = 64
        result = fit_to_width([base, git, ctx, session], 80)
        assert visible_width(result) == 64

        # With tight width, session should be dropped
        result = fit_to_width([base, git, ctx, session], 50)
        assert "test-session-uuid-1234" not in result
        assert visible_width(result) <= 50

    def test_priority_order_preserved(self):
        parts = ["base", " A", " B", " C", " D"]
        # base=4, A=2, B=2, C=2, D=2 => total 12
        # max_width=8 => base + A + B fits (8), C dropped, D dropped
        result = fit_to_width(parts, 8)
        assert result == "base A B"
