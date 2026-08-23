"""Regression guards for shipped settings examples (F-DEAD-003, #132).

The v1.17.0 Python-only migration deleted ~/.claude/statusline.sh, but
config/settings-example.json kept pointing at it — anyone copying the
example got a permanently blank status line. These tests pin the example
to a command that actually exists as a package entry point.
"""

import json
import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _entry_point_names():
    """Extract command names from [project.scripts] in pyproject.toml."""
    pyproject = (_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(r"\[project\.scripts\]\n(.*?)(?:\n\[|\Z)", pyproject, re.DOTALL)
    assert section is not None, "[project.scripts] section missing from pyproject.toml"
    return {line.split("=", 1)[0].strip() for line in section.group(1).splitlines() if "=" in line}


class TestSettingsExample:
    """Tests that config/settings-example.json stays installable."""

    def _load_example(self):
        path = _PROJECT_ROOT / "config" / "settings-example.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_references_installed_command(self):
        command = self._load_example()["statusLine"]["command"]
        assert command in _entry_point_names(), (
            f"settings-example.json references {command!r}, which is not a "
            "[project.scripts] entry point — copying it yields a blank status line"
        )

    def test_no_dead_statusline_script_path(self):
        raw = (_PROJECT_ROOT / "config" / "settings-example.json").read_text(encoding="utf-8")
        assert "statusline.sh" not in raw
