"""Tests for color configuration in Config."""

from claude_statusline.core.config import Config


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
