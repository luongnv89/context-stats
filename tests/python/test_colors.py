"""Tests for configurable colors."""

from claude_statusline.core.colors import (
    BLUE,
    CYAN,
    GREEN,
    MAGENTA,
    RED,
    YELLOW,
    ColorManager,
    parse_color,
)


class TestParseColor:
    """Tests for parse_color()."""

    def test_named_color_red(self):
        assert parse_color("red") == "\033[0;31m"

    def test_named_color_green(self):
        assert parse_color("green") == "\033[0;32m"

    def test_named_color_bright_cyan(self):
        assert parse_color("bright_cyan") == "\033[0;96m"

    def test_named_color_case_insensitive(self):
        assert parse_color("RED") == "\033[0;31m"
        assert parse_color("Green") == "\033[0;32m"

    def test_hex_color(self):
        result = parse_color("#ff5733")
        assert result == "\033[38;2;255;87;51m"

    def test_hex_color_uppercase(self):
        result = parse_color("#FF5733")
        assert result == "\033[38;2;255;87;51m"

    def test_hex_color_black(self):
        result = parse_color("#000000")
        assert result == "\033[38;2;0;0;0m"

    def test_hex_color_white(self):
        result = parse_color("#ffffff")
        assert result == "\033[38;2;255;255;255m"

    def test_invalid_color_returns_none(self):
        assert parse_color("nonexistent") is None

    def test_empty_string_returns_none(self):
        assert parse_color("") is None

    def test_invalid_hex_returns_none(self):
        assert parse_color("#xyz") is None
        assert parse_color("#12345") is None
        assert parse_color("#1234567") is None

    def test_strips_whitespace(self):
        assert parse_color("  red  ") == "\033[0;31m"
        assert parse_color("  #ff5733  ") == "\033[38;2;255;87;51m"


class TestColorManager:
    """Tests for ColorManager with overrides."""

    def test_defaults_without_overrides(self):
        cm = ColorManager(enabled=True)
        assert cm.green == GREEN
        assert cm.yellow == YELLOW
        assert cm.red == RED
        assert cm.blue == BLUE
        assert cm.magenta == MAGENTA
        assert cm.cyan == CYAN

    def test_override_single_color(self):
        custom = "\033[38;2;255;0;0m"
        cm = ColorManager(enabled=True, overrides={"green": custom})
        assert cm.green == custom
        # Others unchanged
        assert cm.yellow == YELLOW
        assert cm.red == RED

    def test_override_multiple_colors(self):
        overrides = {
            "green": "\033[38;2;0;255;0m",
            "red": "\033[38;2;255;0;0m",
        }
        cm = ColorManager(enabled=True, overrides=overrides)
        assert cm.green == overrides["green"]
        assert cm.red == overrides["red"]
        assert cm.yellow == YELLOW  # not overridden

    def test_disabled_returns_empty(self):
        overrides = {"green": "\033[38;2;0;255;0m"}
        cm = ColorManager(enabled=False, overrides=overrides)
        assert cm.green == ""
        assert cm.yellow == ""
        assert cm.bold == ""
        assert cm.reset == ""

    def test_bold_dim_reset_not_overridable(self):
        """bold, dim, reset are always the standard ANSI codes."""
        cm = ColorManager(enabled=True, overrides={"bold": "custom"})
        # bold is not in the _get path, it uses the hardcoded value
        assert cm.bold == "\033[1m"


class TestStructuralColors:
    """Tests for per-element structural colors (tps, delta, model, session).

    Each defaults to the separator color but can be overridden independently.
    """

    STRUCTURAL = ("tps", "delta", "model", "session")

    def test_default_to_separator(self):
        """Without overrides, each structural element inherits the separator color."""
        cm = ColorManager(enabled=True)
        for slot in self.STRUCTURAL:
            assert getattr(cm, slot) == cm.separator

    def test_inherit_overridden_separator(self):
        """When separator is overridden but the element is not, it follows separator."""
        custom = "\033[38;2;1;2;3m"
        cm = ColorManager(enabled=True, overrides={"separator": custom})
        for slot in self.STRUCTURAL:
            assert getattr(cm, slot) == custom

    def test_override_each_independently(self):
        overrides = {
            "tps": "\033[38;2;110;215;210m",
            "delta": "\033[38;2;255;248;220m",
            "model": "\033[38;2;192;192;192m",
            "session": "\033[38;2;139;134;130m",
        }
        cm = ColorManager(enabled=True, overrides=overrides)
        for slot, code in overrides.items():
            assert getattr(cm, slot) == code

    def test_one_override_does_not_affect_others(self):
        """Overriding model leaves tps/delta/session on the separator default."""
        custom = "\033[38;2;192;192;192m"
        cm = ColorManager(enabled=True, overrides={"model": custom})
        assert cm.model == custom
        assert cm.tps == cm.separator
        assert cm.delta == cm.separator
        assert cm.session == cm.separator

    def test_disabled_returns_empty(self):
        cm = ColorManager(enabled=False, overrides={"model": "\033[38;2;1;1;1m"})
        for slot in self.STRUCTURAL:
            assert getattr(cm, slot) == ""
