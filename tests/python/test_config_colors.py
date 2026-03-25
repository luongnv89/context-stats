"""Tests for color configuration and config file I/O in Config."""

from pathlib import Path

from claude_statusline.core.config import Config, _DEFAULT_CONFIG_TEMPLATE


class TestConfigColorOverrides:
    """Tests for loading color overrides from config file."""

    def test_no_color_overrides_by_default(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("autocompact=true\n")
        config = Config.load(config_path=config_file)
        assert config.color_overrides == {}

    def test_named_color_override(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("color_green=bright_cyan\n")
        config = Config.load(config_path=config_file)
        assert "green" in config.color_overrides
        assert config.color_overrides["green"] == "\033[0;96m"

    def test_hex_color_override(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("color_red=#f7768e\n")
        config = Config.load(config_path=config_file)
        assert "red" in config.color_overrides
        assert config.color_overrides["red"] == "\033[38;2;247;118;142m"

    def test_multiple_color_overrides(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("color_green=#7dcfff\ncolor_red=#f7768e\ncolor_blue=bright_blue\n")
        config = Config.load(config_path=config_file)
        assert len(config.color_overrides) == 3
        assert "green" in config.color_overrides
        assert "red" in config.color_overrides
        assert "blue" in config.color_overrides

    def test_invalid_color_ignored(self, tmp_path, capsys):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("color_green=nonexistent_color\n")
        config = Config.load(config_path=config_file)
        assert config.color_overrides == {}

    def test_color_overrides_mixed_with_booleans(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("autocompact=false\ntoken_detail=true\ncolor_yellow=#e0af68\n")
        config = Config.load(config_path=config_file)
        assert config.autocompact is False
        assert config.token_detail is True
        assert "yellow" in config.color_overrides
        assert config.color_overrides["yellow"] == "\033[38;2;224;175;104m"

    def test_color_overrides_in_to_dict(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("color_cyan=#00ffff\n")
        config = Config.load(config_path=config_file)
        d = config.to_dict()
        assert "color_overrides" in d
        assert "cyan" in d["color_overrides"]

    def test_unknown_color_key_ignored(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text("color_purple=magenta\n")
        config = Config.load(config_path=config_file)
        assert config.color_overrides == {}

    def test_all_six_color_slots(self, tmp_path):
        config_file = tmp_path / "statusline.conf"
        config_file.write_text(
            "color_green=green\n"
            "color_yellow=yellow\n"
            "color_red=red\n"
            "color_blue=blue\n"
            "color_magenta=magenta\n"
            "color_cyan=cyan\n"
        )
        config = Config.load(config_path=config_file)
        assert len(config.color_overrides) == 6


class TestConfigDefaultRoundTrip:
    """Tests that the default config template can be written and read back."""

    def test_create_default_and_read_back(self, tmp_path):
        """Verify _create_default() writes a file that Config.load() can re-read."""
        config_file = tmp_path / "statusline.conf"
        # First load triggers _create_default() because the file does not exist
        config1 = Config.load(config_path=config_file)
        assert config_file.exists(), "Default config file should have been created"

        # Verify the file contains Unicode characters (em dash, box drawing)
        content = config_file.read_text(encoding="utf-8")
        assert "\u2014" in content or "\u2500" in content, (
            "Template should contain Unicode characters (em dash or box drawing)"
        )

        # Second load reads the file back — must not raise
        config2 = Config.load(config_path=config_file)

        # Both loads should produce identical settings (first load also
        # reads back the generated template)
        assert config1.autocompact == config2.autocompact
        assert config1.token_detail == config2.token_detail
        assert config1.show_delta == config2.show_delta
        assert config1.show_session == config2.show_session
        assert config1.show_mi == config2.show_mi
        assert config1.color_overrides == config2.color_overrides

    def test_default_config_matches_example(self, tmp_path):
        """Verify _create_default() generates config aligned with examples/statusline.conf."""
        config_file = tmp_path / "statusline.conf"
        Config.load(config_path=config_file)
        content = config_file.read_text(encoding="utf-8")

        # Template must have autocompact=false as default (matching examples/statusline.conf)
        assert "autocompact=false" in content, (
            "Default config should set autocompact=false"
        )

    def test_default_config_contains_expected_keys(self, tmp_path):
        """Verify the generated config has all documented settings."""
        config_file = tmp_path / "statusline.conf"
        Config.load(config_path=config_file)
        content = config_file.read_text(encoding="utf-8")

        for key in ("autocompact=", "token_detail=", "show_delta=",
                     "show_session=", "show_mi=", "mi_curve_beta="):
            assert key in content, f"Default config should contain '{key}'"

    def test_existing_config_not_overwritten(self, tmp_path):
        """Verify _create_default() does not overwrite an existing config file."""
        config_file = tmp_path / "statusline.conf"
        custom_content = "# custom config\nautocompact=true\nshow_mi=true\n"
        config_file.write_text(custom_content, encoding="utf-8")

        Config.load(config_path=config_file)

        # File must still contain the original custom content
        assert config_file.read_text(encoding="utf-8") == custom_content


class TestInlineTemplateSync:
    """Ensure the inline _DEFAULT_CONFIG_TEMPLATE stays in sync with examples/statusline.conf."""

    def test_inline_template_matches_example_file(self):
        """The inline template in config.py must match examples/statusline.conf exactly."""
        repo_root = Path(__file__).resolve().parents[2]
        example_file = repo_root / "examples" / "statusline.conf"
        assert example_file.exists(), (
            f"examples/statusline.conf not found at {example_file}"
        )
        example_content = example_file.read_text(encoding="utf-8")
        assert _DEFAULT_CONFIG_TEMPLATE == example_content, (
            "Inline _DEFAULT_CONFIG_TEMPLATE in config.py is out of sync with "
            "examples/statusline.conf. Update one to match the other."
        )


class TestFirstLoadColorOverrides:
    """Test that first-load (auto-generated config) applies color overrides."""

    def test_first_load_applies_template_colors(self, tmp_path):
        """First load creates default config and reads back color overrides from it."""
        config_file = tmp_path / "statusline.conf"
        # File does not exist yet -- first load triggers _create_default()
        # then _read_config(), which should pick up colors from the template.
        config = Config.load(config_path=config_file)
        assert config_file.exists(), "Default config file should be created on first load"

        # The default template sets color_green=#7dcfff, so the 'green' slot
        # must be present in color_overrides after first load.
        assert "green" in config.color_overrides, (
            "First load should apply color_green from template"
        )
        # Verify it parsed the hex value (38;2;r;g;b format)
        assert "38;2;" in config.color_overrides["green"], (
            "color_green should be parsed as 24-bit ANSI from hex #7dcfff"
        )

    def test_first_load_color_overrides_match_second_load(self, tmp_path):
        """Color overrides from first load must equal those from a second load."""
        config_file = tmp_path / "statusline.conf"
        config1 = Config.load(config_path=config_file)
        config2 = Config.load(config_path=config_file)
        assert config1.color_overrides == config2.color_overrides, (
            "First and second loads should produce identical color_overrides"
        )
