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
    """Tests for fit_to_width() reflow behavior.

    When everything fits, output is a single line (legacy behavior). When
    a part does not fit, it wraps onto a new line instead of being dropped,
    so no information is lost on narrow terminals.
    """

    def test_all_parts_fit(self):
        parts = ["base", " | git", " | ctx"]
        result = fit_to_width(parts, 80)
        assert result == "base | git | ctx"
        assert "\n" not in result

    def test_wraps_lowest_priority_instead_of_dropping(self):
        # base=4, " | git"=6, " | ctx"=6, " | session-uuid-here"=20.
        # At width 25: base + " | git" = 10 fits; + " | ctx" = 16 fits;
        # + " | session-uuid-here" = 36 > 25 -> wraps to line 2 with the
        # leading " | " separator stripped.
        parts = ["base", " | git", " | ctx", " | session-uuid-here"]
        result = fit_to_width(parts, 25)
        # Nothing is dropped — every element is still present.
        assert "base" in result
        assert "git" in result
        assert "ctx" in result
        assert "session-uuid-here" in result
        # It wrapped.
        assert "\n" in result
        lines = result.split("\n")
        assert lines[0] == "base | git | ctx"
        # Wrapped line does not start with a dangling separator.
        assert lines[1] == "session-uuid-here"

    def test_base_always_starts_first_line(self):
        parts = ["very-long-base-string-that-exceeds-width"]
        result = fit_to_width(parts, 10)
        assert result == "very-long-base-string-that-exceeds-width"
        assert "\n" not in result

    def test_empty_parts_skipped(self):
        parts = ["base", "", " | ctx", "", " | session"]
        result = fit_to_width(parts, 30)
        assert result == "base | ctx | session"

    def test_exact_boundary(self):
        parts = ["12345", "67890"]
        result = fit_to_width(parts, 10)
        assert result == "1234567890"
        assert "\n" not in result

    def test_one_char_over_boundary_wraps(self):
        # base=5, second part=6 => 11 > 10, so the second part wraps to its
        # own line (it has no " | " prefix, so nothing is stripped).
        parts = ["12345", "678901"]
        result = fit_to_width(parts, 10)
        assert result == "12345\n678901"

    def test_single_part_wider_than_max_on_own_line(self):
        # A part longer than max_width is emitted whole on its own line,
        # never truncated and without looping forever.
        parts = ["base", " | this-part-is-way-too-long-to-fit-anywhere"]
        result = fit_to_width(parts, 12)
        lines = result.split("\n")
        assert lines[0] == "base"
        # Separator stripped; full content preserved even though it overflows.
        assert lines[1] == "this-part-is-way-too-long-to-fit-anywhere"
        assert "this-part-is-way-too-long-to-fit-anywhere" in result

    def test_empty_parts_list(self):
        assert fit_to_width([], 80) == ""

    def test_realistic_ansi_single_line(self):
        base = "\033[2m[Claude]\033[0m \033[0;34mdir\033[0m"
        git = " | \033[0;35mmain\033[0m"
        ctx = " | \033[0;32m150.0k (75.0%)\033[0m"
        session = " | \033[2mtest-session-uuid-1234\033[0m"

        # base=[Claude] dir = 12, git= | main = 7, ctx= | 150.0k (75.0%) = 17,
        # session= | test-session-uuid-1234 = 25 => total = 61
        result = fit_to_width([base, git, ctx, session], 80)
        assert visible_width(result) == 61
        assert "\n" not in result

    def test_realistic_ansi_wraps_and_preserves_color(self):
        base = "\033[2m[Claude]\033[0m \033[0;34mdir\033[0m"
        git = " | \033[0;35mmain\033[0m"
        ctx = " | \033[0;32m150.0k (75.0%)\033[0m"
        session = " | \033[2mtest-session-uuid-1234\033[0m"

        # With a tight width, session wraps in instead of being dropped.
        result = fit_to_width([base, git, ctx, session], 40)
        assert "test-session-uuid-1234" in result
        assert "\n" in result
        # Every wrapped line individually fits the width.
        for line in result.split("\n"):
            assert visible_width(line) <= 40
        # ANSI color codes are preserved through the wrap.
        assert "\033[2m" in result
        assert "\033[0;32m" in result

    def test_no_wrapped_line_starts_with_separator(self):
        parts = ["base", " | aaaa", " | bbbb", " | cccc", " | dddd"]
        result = fit_to_width(parts, 14)
        for line in result.split("\n"):
            assert not line.startswith(" | ")

    def test_priority_order_preserved_across_lines(self):
        parts = ["base", " | A", " | B", " | C", " | D"]
        # base=4, " | A"=4, " | B"=4, " | C"=4, " | D"=4.
        # width=12 => "base | A" (8) + " | B" (12) fits; " | C" wraps,
        # "C | D" on line 2. Order is preserved, nothing dropped.
        result = fit_to_width(parts, 12)
        assert result == "base | A | B\nC | D"


class TestStandalonePackageParity:
    """The reflow logic is duplicated between the installable package and the
    standalone script and MUST stay in sync (see CLAUDE.md "Sync Points").
    This guards against the two fit_to_width implementations diverging — a
    subtle drift could otherwise pass each impl's own tests independently.
    Acceptance criterion #4 of issue #88: identical behavior in both.
    """

    # Representative inputs: single-line fit, exact boundary, wrap with the
    # separator-strip path, oversized single part, empty parts, and realistic
    # ANSI-colored parts at both wide and narrow widths.
    _CASES = [
        ([], 80),
        (["base"], 5),
        (["base", " | git", " | ctx"], 80),
        (["base", " | git", " | ctx", " | session-uuid-here"], 25),
        (["12345", "67890"], 10),
        (["12345", "678901"], 10),
        (["base", " | this-part-is-way-too-long-to-fit"], 12),
        (["base", "", " | ctx", "", " | session"], 30),
        (["base", " | A", " | B", " | C", " | D"], 12),
        (
            [
                "\033[2m[Claude]\033[0m \033[0;34mdir\033[0m",
                " | \033[0;35mmain\033[0m",
                " | \033[0;32m150.0k (75.0%)\033[0m",
                " | \033[2mtest-session-uuid-1234\033[0m",
            ],
            40,
        ),
        (
            [
                "\033[2m[Claude]\033[0m \033[0;34mdir\033[0m",
                " | \033[0;35mmain\033[0m",
                " | \033[0;32m150.0k (75.0%)\033[0m",
                " | \033[2mtest-session-uuid-1234\033[0m",
            ],
            200,
        ),
    ]

    def test_fit_to_width_identical_across_impls(self):
        # conftest.py puts the project root on sys.path so the standalone
        # script imports as a module.
        from scripts.statusline import fit_to_width as std_fit

        from claude_statusline.formatters.layout import fit_to_width as pkg_fit

        for parts, width in self._CASES:
            assert pkg_fit(parts, width) == std_fit(parts, width), (
                f"fit_to_width diverged between package and standalone for "
                f"parts={parts!r} width={width}"
            )

    def test_visible_width_identical_across_impls(self):
        from scripts.statusline import visible_width as std_vw

        from claude_statusline.formatters.layout import visible_width as pkg_vw

        for s in ["plain", "\033[0;32mgreen\033[0m", "", "○⚡"]:
            assert pkg_vw(s) == std_vw(s)

    def test_part_separator_identical_across_impls(self):
        from scripts.statusline import _PART_SEPARATOR as std_sep

        from claude_statusline.formatters.layout import _PART_SEPARATOR as pkg_sep

        assert pkg_sep == std_sep == " | "
