"""Tests for ``context-stats doctor`` (issue #186).

Covers the diagnosis path (missing/invalid/foreign statusLine wiring, and the
higher-precedence project settings files Claude Code merges over the user
one), the ``--fix`` repair path (idempotency, key merging, symlink/mode
preservation, backups, --force), and the sandboxed smoke render that must not
report a false negative on a ``pip install --user`` layout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_statusline.cli import doctor
from claude_statusline.cli.context_stats import _KNOWN_ACTIONS, _normalize_argv
from claude_statusline.cli.doctor import (
    DEFAULT_STATUSLINE_COMMAND,
    CheckResult,
    DoctorReport,
    apply_fix,
    check_entry_points,
    check_runtime_state,
    check_settings,
    check_smoke_render,
    render_report,
    run_doctor,
    settings_path,
)
from claude_statusline.core.colors import ColorManager

# Mode-preservation assertions are POSIX-only. Windows `os.chmod` honors just
# the read-only bit, and `stat()` reports 0o666 for any writable file, so a
# Windows run can neither set nor observe 0o644/0o600 — the assertion cannot
# hold, and the weakened form (`mode & 0o600`) would pass vacuously for every
# writable file and prove nothing about preservation.
posix_modes_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows cannot express POSIX permission bits: os.chmod honors only the "
    "read-only bit and stat() reports 0o666 for any writable file",
)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect HOME and cwd so settings/state paths resolve inside tmp_path.

    The cwd move matters as much as HOME: doctor now also probes the
    project-level ``./.claude/settings*.json`` files, so a test left standing
    in the repository would read whatever the checkout happens to contain.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    monkeypatch.chdir(project)
    return tmp_path


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _statuses(report: DoctorReport, section: str) -> list[str]:
    for name, results in report.sections:
        if name == section:
            return [r.status for r in results]
    return []


def _messages(report: DoctorReport, section: str) -> str:
    for name, results in report.sections:
        if name == section:
            return "\n".join(r.message for r in results)
    return ""


class TestDoctorReport:
    def test_add_groups_by_section(self):
        report = DoctorReport()
        report.add("A", CheckResult("pass", "one"))
        report.add("B", CheckResult("fail", "two"))
        report.add("A", CheckResult("warn", "three"))
        assert [name for name, _ in report.sections] == ["A", "B"]
        assert _statuses(report, "A") == ["pass", "warn"]

    def test_counts(self):
        report = DoctorReport()
        report.add("A", CheckResult("pass", "p"))
        report.add("A", CheckResult("warn", "w"))
        report.add("A", CheckResult("fail", "f"))
        assert report.counts() == (1, 1, 1)


class TestCheckSettings:
    def test_missing_file_is_the_headline_failure(self, fake_home):
        report = DoctorReport()
        check_settings(report)
        assert "fail" in _statuses(report, "Claude Code settings")
        assert "statusLine is not configured" in _messages(report, "Claude Code settings")

    def test_absent_file_warns_but_still_reports_the_wiring_gap(self, fake_home):
        report = DoctorReport()
        check_settings(report)
        statuses = _statuses(report, "Claude Code settings")
        assert statuses == ["warn", "fail"]

    def test_invalid_json_fails_without_claiming_statusline_state(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        report = DoctorReport()
        check_settings(report)
        assert _statuses(report, "Claude Code settings") == ["fail"]
        assert "not valid JSON" in _messages(report, "Claude Code settings")

    def test_non_object_json_fails(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text("[1, 2]", encoding="utf-8")
        report = DoctorReport()
        check_settings(report)
        assert "must contain a JSON object" in _messages(report, "Claude Code settings")

    def test_empty_file_is_treated_as_no_settings(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text("   \n", encoding="utf-8")
        report = DoctorReport()
        check_settings(report)
        assert "statusLine is not configured" in _messages(report, "Claude Code settings")

    def test_wrong_type_fails(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"statusLine": {"type": "static", "command": "x"}}), encoding="utf-8"
        )
        report = DoctorReport()
        check_settings(report)
        assert 'expected "command"' in _messages(report, "Claude Code settings")

    def test_unresolvable_command_fails(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"statusLine": {"type": "command", "command": "/nope/definitely-not-here"}}),
            encoding="utf-8",
        )
        report = DoctorReport()
        check_settings(report)
        assert "does not resolve" in _messages(report, "Claude Code settings")

    def test_resolvable_absolute_path_passes(self, fake_home, tmp_path):
        script = tmp_path / DEFAULT_STATUSLINE_COMMAND
        script.write_text("#!/bin/sh\n", encoding="utf-8")
        script.chmod(0o755)
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"statusLine": {"type": "command", "command": str(script)}}),
            encoding="utf-8",
        )
        report = DoctorReport()
        check_settings(report)
        assert "fail" not in _statuses(report, "Claude Code settings")

    def test_foreign_statusline_warns(self, fake_home, tmp_path, monkeypatch):
        other = tmp_path / "some-other-statusline"
        other.write_text("#!/bin/sh\n", encoding="utf-8")
        other.chmod(0o755)
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"statusLine": {"type": "command", "command": str(other)}}),
            encoding="utf-8",
        )
        report = DoctorReport()
        check_settings(report)
        assert "warn" in _statuses(report, "Claude Code settings")
        assert "different status line" in _messages(report, "Claude Code settings")

    def test_unreadable_file_is_reported_not_crashed(self, fake_home, monkeypatch):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text("{}", encoding="utf-8")

        def boom(*_a, **_k):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", boom)
        report = DoctorReport()
        check_settings(report)
        assert "cannot read" in _messages(report, "Claude Code settings")

    def test_non_utf8_file_is_reported_not_crashed(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_bytes(b'{"a": "\xff\xfe"}')
        report = DoctorReport()
        check_settings(report)
        assert _statuses(report, "Claude Code settings") == ["fail"]
        assert "not valid UTF-8" in _messages(report, "Claude Code settings")


class TestApplyFix:
    def test_creates_settings_when_absent(self, fake_home):
        apply_fix(DoctorReport(), force=False)
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        assert data["statusLine"] == {
            "type": "command",
            "command": DEFAULT_STATUSLINE_COMMAND,
        }

    def test_preserves_unrelated_keys_and_backs_up(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"theme": "dark", "hooks": {"a": 1}}), encoding="utf-8")

        report = DoctorReport()
        apply_fix(report, force=False)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["theme"] == "dark"
        assert data["hooks"] == {"a": 1}
        assert data["statusLine"]["command"] == DEFAULT_STATUSLINE_COMMAND

        backups = list(path.parent.glob("settings.json.bak.*"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text(encoding="utf-8")) == {
            "theme": "dark",
            "hooks": {"a": 1},
        }

    def test_is_idempotent_and_skips_backup(self, fake_home):
        apply_fix(DoctorReport(), force=False)
        first = settings_path().read_text(encoding="utf-8")

        report = DoctorReport()
        apply_fix(report, force=False)
        assert "nothing to do" in _messages(report, "Repair")
        assert settings_path().read_text(encoding="utf-8") == first
        assert list(settings_path().parent.glob("settings.json.bak.*")) == []

    def test_refuses_to_clobber_foreign_statusline(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        original = {"statusLine": {"type": "command", "command": "other-tool"}}
        path.write_text(json.dumps(original), encoding="utf-8")

        report = DoctorReport()
        apply_fix(report, force=False)

        assert "fail" in _statuses(report, "Repair")
        assert "left untouched" in _messages(report, "Repair")
        assert json.loads(path.read_text(encoding="utf-8")) == original

    def test_force_replaces_foreign_statusline(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"statusLine": {"type": "command", "command": "other-tool"}}),
            encoding="utf-8",
        )
        apply_fix(DoctorReport(), force=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["statusLine"]["command"] == DEFAULT_STATUSLINE_COMMAND

    @pytest.mark.parametrize(
        "broken",
        [
            "claude-statusline.sh",  # bare string: not an object at all
            {},  # empty dict
            {"type": "command"},  # dict without a command
            {"type": "command", "command": ""},  # blank command
        ],
        ids=["string", "empty-dict", "no-command", "blank-command"],
    )
    def test_plain_fix_repairs_what_check_settings_calls_unconfigured(self, fake_home, broken):
        """Shapes ``check_settings`` reports as 'not configured' must be repairable.

        The diagnosis tells users to run plain ``doctor --fix`` for these, so
        the repair gate refusing without ``--force`` would dead-end the tool's
        own remediation (issue #186 review feedback).
        """
        path = settings_path()
        path.parent.mkdir(parents=True)
        original = {"theme": "dark", "statusLine": broken}
        path.write_text(json.dumps(original), encoding="utf-8")

        report = DoctorReport()
        apply_fix(report, force=False)

        assert _statuses(report, "Repair") == ["pass", "pass", "warn"]
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["theme"] == "dark"
        assert data["statusLine"] == {
            "type": "command",
            "command": DEFAULT_STATUSLINE_COMMAND,
        }

    def test_dict_with_truthy_command_but_wrong_type_still_needs_force(self, fake_home):
        """A truthy command is a working foreign block even with a bad type.

        ``check_settings`` fails on the wrong type and hints ``--fix --force``
        for the user file, so the refusal gate must agree that this shape is
        configured and require ``--force`` to displace it.
        """
        path = settings_path()
        path.parent.mkdir(parents=True)
        original = {"statusLine": {"type": "widget", "command": "other-tool"}}
        path.write_text(json.dumps(original), encoding="utf-8")

        report = DoctorReport()
        apply_fix(report, force=False)

        assert "left untouched" in _messages(report, "Repair")
        assert json.loads(path.read_text(encoding="utf-8")) == original

    def test_refuses_to_write_over_invalid_json(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")

        report = DoctorReport()
        apply_fix(report, force=True)

        assert "refusing to write" in _messages(report, "Repair")
        assert path.read_text(encoding="utf-8") == "{broken"

    def test_refuses_to_write_over_non_utf8_settings(self, fake_home):
        path = settings_path()
        path.parent.mkdir(parents=True)
        raw = b'{"a": "\xff\xfe"}'
        path.write_bytes(raw)

        report = DoctorReport()
        apply_fix(report, force=True)

        assert "fail" in _statuses(report, "Repair")
        assert "refusing to write" in _messages(report, "Repair")
        assert "not valid UTF-8" in _messages(report, "Repair")
        assert path.read_bytes() == raw
        assert list(path.parent.glob("settings.json.bak.*")) == []

    def test_backup_collision_picks_a_fresh_name(self, fake_home, monkeypatch):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        monkeypatch.setattr(doctor.time, "strftime", lambda _fmt: "FIXED")
        (path.parent / "settings.json.bak.FIXED").write_text("older", encoding="utf-8")

        apply_fix(DoctorReport(), force=False)
        assert (path.parent / "settings.json.bak.FIXED.1").exists()

    def test_backup_failure_is_reported(self, fake_home, monkeypatch):
        path = settings_path()
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        monkeypatch.setattr(
            doctor.shutil, "copy2", lambda *_a, **_k: (_ for _ in ()).throw(OSError("nope"))
        )
        report = DoctorReport()
        apply_fix(report, force=False)
        assert "could not back up" in _messages(report, "Repair")

    def test_write_failure_is_reported(self, fake_home, monkeypatch):
        monkeypatch.setattr(
            doctor, "_write_settings", lambda *_a, **_k: (_ for _ in ()).throw(OSError("full"))
        )
        report = DoctorReport()
        apply_fix(report, force=False)
        assert "could not write" in _messages(report, "Repair")

    def test_write_settings_cleans_up_temp_on_failure(self, fake_home, monkeypatch):
        path = settings_path()
        path.parent.mkdir(parents=True)
        monkeypatch.setattr(
            doctor.json, "dump", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError):
            doctor._write_settings(path, {"a": 1})
        assert list(path.parent.glob("settings.json*.tmp")) == []


class TestEntryPointsAndState:
    def test_entry_points_fail_when_absent(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda _n: None)
        report = DoctorReport()
        check_entry_points(report)
        assert _statuses(report, "Entry points") == ["fail", "fail"]

    def test_entry_points_pass_when_present(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda n: f"/usr/bin/{n}")
        report = DoctorReport()
        check_entry_points(report)
        assert _statuses(report, "Entry points") == ["pass", "pass"]

    def test_runtime_state_warns_on_fresh_install(self, fake_home):
        report = DoctorReport()
        check_runtime_state(report)
        assert _statuses(report, "Runtime state") == ["warn", "warn"]

    def test_runtime_state_counts_sessions(self, fake_home):
        state = fake_home / ".claude" / "statusline"
        state.mkdir(parents=True)
        (state / "statusline.abc.state").write_text("", encoding="utf-8")
        (fake_home / ".claude" / "statusline.conf").write_text("", encoding="utf-8")
        report = DoctorReport()
        check_runtime_state(report)
        assert _statuses(report, "Runtime state") == ["pass", "pass"]
        assert "1 session file(s)" in _messages(report, "Runtime state")


class TestSmokeRender:
    def test_pass_when_project_dir_is_echoed(self, monkeypatch):
        monkeypatch.setattr(doctor, "_resolve_statusline_command", lambda: ["/bin/echo"])

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, "proj doctor-smoke-project ok", "")

        monkeypatch.setattr(doctor.subprocess, "run", fake_run)
        report = DoctorReport()
        check_smoke_render(report)
        assert _statuses(report, "Statusline render") == ["pass"]

    def test_fail_on_crash_fallback_output(self, monkeypatch):
        monkeypatch.setattr(doctor, "_resolve_statusline_command", lambda: ["/bin/echo"])
        monkeypatch.setattr(
            doctor.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "[Claude] ~", ""),
        )
        report = DoctorReport()
        check_smoke_render(report)
        assert _statuses(report, "Statusline render") == ["fail"]
        assert "crash fallback" in _messages(report, "Statusline render")

    def test_fail_on_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(doctor, "_resolve_statusline_command", lambda: ["/bin/echo"])
        monkeypatch.setattr(
            doctor.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 3, "", "Traceback\nboom"),
        )
        report = DoctorReport()
        check_smoke_render(report)
        assert "exited 3" in _messages(report, "Statusline render")

    def test_timeout_is_reported(self, monkeypatch):
        monkeypatch.setattr(doctor, "_resolve_statusline_command", lambda: ["/bin/echo"])

        def boom(*_a, **_k):
            raise subprocess.TimeoutExpired("cmd", 20)

        monkeypatch.setattr(doctor.subprocess, "run", boom)
        report = DoctorReport()
        check_smoke_render(report)
        assert "timed out" in _messages(report, "Statusline render")

    def test_oserror_is_reported(self, monkeypatch):
        monkeypatch.setattr(doctor, "_resolve_statusline_command", lambda: ["/bin/echo"])

        def boom(*_a, **_k):
            raise OSError("exec format error")

        monkeypatch.setattr(doctor.subprocess, "run", boom)
        report = DoctorReport()
        check_smoke_render(report)
        assert "could not run" in _messages(report, "Statusline render")

    def test_no_runnable_command(self, monkeypatch):
        monkeypatch.setattr(doctor, "_resolve_statusline_command", lambda: None)
        report = DoctorReport()
        check_smoke_render(report)
        assert _statuses(report, "Statusline render") == ["fail"]

    def test_sandbox_preserves_python_user_base(self, monkeypatch):
        """Regression: overriding HOME alone breaks `pip install --user` imports."""
        monkeypatch.setattr(doctor, "_resolve_statusline_command", lambda: ["/bin/echo"])
        monkeypatch.setattr(doctor, "_user_base", lambda: "/real/user/base")
        captured = {}

        def fake_run(argv, **kwargs):
            captured.update(kwargs.get("env", {}))
            return subprocess.CompletedProcess(argv, 0, "doctor-smoke-project", "")

        monkeypatch.setattr(doctor.subprocess, "run", fake_run)
        check_smoke_render(DoctorReport())
        assert captured["PYTHONUSERBASE"] == "/real/user/base"
        assert captured["HOME"] != "/real/user/base"

    def test_resolve_prefers_console_script(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda _n: "/usr/bin/claude-statusline")
        assert doctor._resolve_statusline_command() == ["/usr/bin/claude-statusline"]

    def test_resolve_falls_back_to_module(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda _n: None)
        argv = doctor._resolve_statusline_command()
        assert argv is not None
        assert argv[1:] == ["-m", "claude_statusline"]

    def test_user_base_is_a_string(self):
        assert isinstance(doctor._user_base(), str)


class TestRunDoctor:
    def test_unknown_flag_exits_one(self, capsys):
        assert run_doctor(["--bogus"], ColorManager(enabled=False)) == 1
        assert "Unknown flag" in capsys.readouterr().err

    def test_help_exits_zero(self, capsys):
        assert run_doctor(["--help"], ColorManager(enabled=False)) == 0
        assert "context-stats doctor" in capsys.readouterr().out

    def test_force_without_fix_is_rejected(self, capsys):
        assert run_doctor(["--force"], ColorManager(enabled=False)) == 1
        assert "--force requires --fix" in capsys.readouterr().err

    def test_no_color_flag_is_accepted(self, fake_home, monkeypatch, capsys):
        monkeypatch.setattr(doctor.shutil, "which", lambda n: f"/usr/bin/{n}")
        monkeypatch.setattr(doctor, "check_smoke_render", lambda r: None)
        rc = run_doctor(["--no-color"], ColorManager(enabled=False))
        assert rc == 1  # statusLine still unconfigured
        assert "statusLine is not configured" in capsys.readouterr().out

    def test_fix_makes_a_failing_install_pass(self, fake_home, monkeypatch, capsys):
        monkeypatch.setattr(doctor.shutil, "which", lambda n: f"/usr/bin/{n}")
        monkeypatch.setattr(doctor, "check_smoke_render", lambda r: None)

        assert run_doctor([], ColorManager(enabled=False)) == 1
        assert run_doctor(["--fix"], ColorManager(enabled=False)) == 0
        out = capsys.readouterr().out
        assert "Restart Claude Code" in out

    def test_render_report_summarizes_success(self, capsys):
        report = DoctorReport()
        report.add("A", CheckResult("pass", "fine"))
        render_report(report, ColorManager(enabled=False))
        assert "All checks passed" in capsys.readouterr().out


class TestStatusLineKeyMerging:
    """N1: an already-correct block with sibling keys must not be clobbered."""

    def test_extra_keys_count_as_already_configured(self, fake_home):
        path = settings_path()
        original = {
            "statusLine": {
                "type": "command",
                "command": DEFAULT_STATUSLINE_COMMAND,
                "padding": 0,
            }
        }
        _write_json(path, original)

        report = DoctorReport()
        apply_fix(report, force=False)

        assert _statuses(report, "Repair") == ["pass"]
        assert "nothing to do" in _messages(report, "Repair")
        assert json.loads(path.read_text(encoding="utf-8")) == original
        assert list(path.parent.glob("settings.json.bak.*")) == []

    def test_force_merges_sibling_keys_of_a_foreign_block(self, fake_home):
        path = settings_path()
        _write_json(path, {"statusLine": {"type": "command", "command": "other", "padding": 0}})

        apply_fix(DoctorReport(), force=True)

        block = json.loads(path.read_text(encoding="utf-8"))["statusLine"]
        assert block["command"] == DEFAULT_STATUSLINE_COMMAND
        assert block["type"] == "command"
        assert block["padding"] == 0  # sibling key survives the repair

    def test_non_dict_statusline_is_replaced_wholesale(self, fake_home):
        path = settings_path()
        _write_json(path, {"statusLine": "claude-statusline"})

        apply_fix(DoctorReport(), force=True)

        assert json.loads(path.read_text(encoding="utf-8"))["statusLine"] == {
            "type": "command",
            "command": DEFAULT_STATUSLINE_COMMAND,
        }


class TestWriteSettingsPreservation:
    """N2: --fix must not sever a dotfiles symlink or reset the file mode."""

    def test_symlinked_settings_keeps_its_link(self, fake_home, tmp_path):
        dotfiles = tmp_path / "dotfiles"
        dotfiles.mkdir()
        real = dotfiles / "settings.json"
        real.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(real)

        apply_fix(DoctorReport(), force=False)

        assert path.is_symlink()
        # Compare resolved identity rather than the literal link text: Windows
        # `readlink()` returns the extended-length `\\?\C:\...` spelling of the
        # same target, and `resolve()` preserves that prefix once present.
        # `samefile` pins the link to exactly this target on every platform.
        assert os.path.samefile(path, real)
        written = json.loads(real.read_text(encoding="utf-8"))
        assert written["theme"] == "dark"
        assert written["statusLine"]["command"] == DEFAULT_STATUSLINE_COMMAND

    @posix_modes_only
    def test_group_readable_mode_is_preserved(self, fake_home):
        path = settings_path()
        _write_json(path, {"theme": "dark"})
        path.chmod(0o644)

        apply_fix(DoctorReport(), force=False)

        assert path.stat().st_mode & 0o777 == 0o644

    @posix_modes_only
    def test_owner_only_mode_stays_owner_only(self, fake_home):
        path = settings_path()
        _write_json(path, {"theme": "dark"})
        path.chmod(0o600)

        apply_fix(DoctorReport(), force=False)

        assert path.stat().st_mode & 0o777 == 0o600

    @posix_modes_only
    def test_new_file_defaults_to_owner_only(self, fake_home):
        apply_fix(DoctorReport(), force=False)
        assert settings_path().stat().st_mode & 0o777 == 0o600

    @posix_modes_only
    def test_symlinked_settings_keeps_the_target_mode(self, fake_home, tmp_path):
        dotfiles = tmp_path / "dotfiles"
        dotfiles.mkdir()
        real = dotfiles / "settings.json"
        real.write_text("{}", encoding="utf-8")
        real.chmod(0o644)
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(real)

        apply_fix(DoctorReport(), force=False)

        assert real.stat().st_mode & 0o777 == 0o644


class TestSettingsPrecedence:
    """N3: project settings files outrank ~/.claude/settings.json."""

    @staticmethod
    def _statusline(command: str) -> dict:
        return {"statusLine": {"type": "command", "command": command}}

    def test_project_local_statusline_counts_as_configured(self, fake_home, tmp_path):
        local = Path.cwd() / ".claude" / "settings.local.json"
        _write_json(local, self._statusline(DEFAULT_STATUSLINE_COMMAND))
        _write_json(settings_path(), {"theme": "dark"})

        report = DoctorReport()
        check_settings(report)

        messages = _messages(report, "Claude Code settings")
        assert "statusLine is not configured" not in messages
        assert "pass" in _statuses(report, "Claude Code settings")
        assert str(local) in messages  # the source file is named

    def test_project_shared_statusline_counts_as_configured(self, fake_home):
        shared = Path.cwd() / ".claude" / "settings.json"
        _write_json(shared, self._statusline(DEFAULT_STATUSLINE_COMMAND))

        report = DoctorReport()
        check_settings(report)

        messages = _messages(report, "Claude Code settings")
        assert "statusLine is not configured" not in messages
        assert str(shared) in messages

    def test_higher_precedence_definition_warns_about_the_override(self, fake_home):
        _write_json(settings_path(), self._statusline(DEFAULT_STATUSLINE_COMMAND))
        local = Path.cwd() / ".claude" / "settings.local.json"
        _write_json(local, self._statusline(DEFAULT_STATUSLINE_COMMAND))

        report = DoctorReport()
        check_settings(report)

        messages = _messages(report, "Claude Code settings")
        assert "warn" in _statuses(report, "Claude Code settings")
        assert "takes precedence over" in messages
        assert str(local) in messages

    def test_local_file_wins_over_project_file(self, fake_home):
        _write_json(Path.cwd() / ".claude" / "settings.json", self._statusline("shared-tool"))
        _write_json(
            Path.cwd() / ".claude" / "settings.local.json",
            self._statusline(DEFAULT_STATUSLINE_COMMAND),
        )

        report = DoctorReport()
        check_settings(report)

        messages = _messages(report, "Claude Code settings")
        assert f"statusLine.command = {DEFAULT_STATUSLINE_COMMAND}" in messages
        assert "shared-tool" not in messages.split("statusLine.command =")[-1]

    def test_malformed_project_file_warns_instead_of_crashing(self, fake_home):
        broken = Path.cwd() / ".claude" / "settings.local.json"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text("{not json", encoding="utf-8")
        _write_json(settings_path(), self._statusline(DEFAULT_STATUSLINE_COMMAND))

        report = DoctorReport()
        check_settings(report)

        statuses = _statuses(report, "Claude Code settings")
        messages = _messages(report, "Claude Code settings")
        assert "warn" in statuses
        assert "ignoring higher-precedence file" in messages
        assert str(broken) in messages
        # The user file's own check still succeeds.
        assert f"statusLine.command = {DEFAULT_STATUSLINE_COMMAND}" in messages

    def test_project_block_failure_points_at_the_project_file(self, fake_home):
        local = Path.cwd() / ".claude" / "settings.local.json"
        _write_json(local, self._statusline("/nope/definitely-not-here"))

        report = DoctorReport()
        check_settings(report)

        messages = _messages(report, "Claude Code settings")
        assert "does not resolve" in messages
        assert f"(from {local})" in messages

    def test_apply_fix_warns_that_the_repair_may_be_overridden(self, fake_home):
        local = Path.cwd() / ".claude" / "settings.local.json"
        _write_json(local, self._statusline("other-tool"))

        report = DoctorReport()
        apply_fix(report, force=False)

        assert "warn" in _statuses(report, "Repair")
        assert "may not take effect" in _messages(report, "Repair")
        # The write target is unchanged: the user file still gets the block.
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        assert data["statusLine"]["command"] == DEFAULT_STATUSLINE_COMMAND

    def test_cwd_equal_to_home_does_not_self_override(self, fake_home, monkeypatch):
        monkeypatch.chdir(fake_home)
        _write_json(settings_path(), self._statusline(DEFAULT_STATUSLINE_COMMAND))

        report = DoctorReport()
        check_settings(report)

        assert "takes precedence over" not in _messages(report, "Claude Code settings")

    def test_project_settings_paths_are_cwd_relative(self, fake_home):
        paths = doctor.project_settings_paths()
        assert paths == (
            Path.cwd() / ".claude" / "settings.json",
            Path.cwd() / ".claude" / "settings.local.json",
        )


class TestCliWiring:
    def test_doctor_is_a_known_action(self):
        assert "doctor" in _KNOWN_ACTIONS

    def test_normalize_argv_routes_doctor(self):
        action, session_id, remaining = _normalize_argv(["doctor", "--fix"])
        assert action == "doctor"
        assert session_id is None
        assert remaining == ["--fix"]
