"""Tests for stdin trust-boundary hardening (issues #127, #128, #131).

Covers, in BOTH mirrored implementations (scripts/statusline.py and
src/claude_statusline/cli/statusline.py):

- #127 / F-BUG-002: session_id validation before any state-path use.
- #128 / F-BUG-003: explicit JSON null treated like an absent key.
- #128 / F-BUG-004: render catch-all (fallback line on stdout, traceback
  on stderr only).
- #131 / F-SEC-002: project_dir resolved + verified to exist before any
  git/gh subprocess runs with it.
- #131 / F-SEC-003: newly created state files get owner-only 0600 perms.
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "statusline.py"

HOSTILE_SESSION_IDS = ["../../evil", "a/b", "a\\b", "..hidden", "sess\0id"]


def strip_ansi(s: str) -> str:
    import re

    return re.compile(r"\033\[[0-9;]*m").sub("", s)


def run_script(input_data: dict, env_overrides: dict | None = None):
    """Run scripts/statusline.py with ``input_data`` as stdin JSON."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if env_overrides:
        home = env_overrides.get("HOME")
        if home:
            # ntpath.expanduser/Path.home() prefer USERPROFILE over HOME, so a
            # HOME-only override does not isolate the state dir on Windows.
            env["USERPROFILE"] = home
            drive, path = os.path.splitdrive(home)
            if drive or path:
                env["HOMEDRIVE"] = drive
                env["HOMEPATH"] = path
        env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    return result.stdout.strip(), result.returncode, result.stderr


def full_payload(project_dir: str, session_id: str | None = "ok-session") -> dict:
    """A payload rich enough to reach the state-write site."""
    return {
        "session_id": session_id,
        "model": {"id": "claude-test", "display_name": "Test Model"},
        "workspace": {"current_dir": project_dir, "project_dir": project_dir},
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 10000,
                "cache_creation_input_tokens": 500,
                "cache_read_input_tokens": 200,
                "output_tokens": 900,
            },
        },
        "cost": {"total_cost_usd": 0.42, "total_lines_added": 3, "total_lines_removed": 1},
    }


# ---------------------------------------------------------------------------
# Issue #127 / F-BUG-002 — session_id validation
# ---------------------------------------------------------------------------


class TestStandaloneSessionIdValidation:
    """The standalone script must reject hostile session_ids (#127)."""

    @pytest.mark.parametrize("bad_id", HOSTILE_SESSION_IDS)
    def test_hostile_session_id_renders_without_crash(self, bad_id, tmp_path):
        payload = full_payload(str(tmp_path), session_id=bad_id)
        out, code, _err = run_script(payload, {"HOME": str(tmp_path)})
        assert code == 0
        # Render degrades gracefully (no traceback on stdout, no fallback line)
        assert "Traceback" not in out
        assert "[Claude] ~" not in out

    def test_hostile_session_id_writes_nothing_outside_state_dir(self, tmp_path):
        """A scripted stdin payload with ../evil must not escape the state dir."""
        payload = full_payload(str(tmp_path), session_id="../../evil")
        out, code, _err = run_script(payload, {"HOME": str(tmp_path)})
        assert code == 0
        escaped = [p for p in tmp_path.rglob("*") if p.is_file() and "evil" in p.name]
        assert escaped == []
        state_files = (
            list((tmp_path / ".claude").rglob("*.state")) if (tmp_path / ".claude").exists() else []
        )
        for f in state_files:
            assert "evil" not in f.name

    def test_warning_goes_to_stderr(self, tmp_path):
        payload = full_payload(str(tmp_path), session_id="../evil")
        _out, code, err = run_script(payload, {"HOME": str(tmp_path)})
        assert code == 0
        assert "Invalid session_id" in err

    def test_valid_session_id_still_persists(self, tmp_path):
        payload = full_payload(str(tmp_path), session_id="good-session-1")
        _out, code, _err = run_script(payload, {"HOME": str(tmp_path)})
        assert code == 0
        expected = tmp_path / ".claude" / "statusline" / "statusline.good-session-1.state"
        assert expected.exists()


class TestPackageSessionIdValidation:
    """The package CLI must reject hostile session_ids identically (#127)."""

    def test_hostile_session_id_degrades_to_none(self, tmp_path, monkeypatch, capsys):
        from claude_statusline.cli import statusline as pkg_statusline
        from claude_statusline.core.state import StateFile

        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        payload = full_payload(str(tmp_path), session_id="../../evil")
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("COLUMNS", "200")

        pkg_statusline.main()  # must not raise

        err = capsys.readouterr().err
        assert "Invalid session_id" in err
        written = list(tmp_path.rglob("*evil*"))
        assert written == []

    def test_valid_session_id_still_used(self, tmp_path, monkeypatch, capsys):
        from claude_statusline.cli import statusline as pkg_statusline
        from claude_statusline.core.state import StateFile

        state_dir = tmp_path / "state"
        monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        payload = full_payload(str(tmp_path), session_id="pkg-good-session")
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        monkeypatch.setenv("COLUMNS", "200")

        pkg_statusline.main()

        assert (state_dir / "statusline.pkg-good-session.state").exists()


NON_STRING_SESSION_IDS = [123, 4.2, True, {"k": "../../evil"}, ["a", "/b"]]


class TestNonStringSessionIds:
    """Non-string session_ids must degrade per-field, never crash or bypass (#127)."""

    @pytest.mark.parametrize("bad_id", NON_STRING_SESSION_IDS)
    def test_script_non_string_session_id_degrades(self, bad_id, tmp_path):
        payload = full_payload(str(tmp_path), session_id=bad_id)
        out, code, err = run_script(payload, {"HOME": str(tmp_path)})
        assert code == 0
        assert "Invalid session_id" in err
        assert "[Claude] ~" not in out
        assert "Traceback" not in err
        escaped = [p for p in tmp_path.rglob("*") if p.is_file() and "evil" in p.name]
        assert escaped == []

    @pytest.mark.parametrize("bad_id", NON_STRING_SESSION_IDS)
    def test_package_non_string_session_id_degrades(self, bad_id, tmp_path, monkeypatch, capsys):
        from claude_statusline.cli import statusline as pkg_statusline
        from claude_statusline.core.state import StateFile

        state_dir = tmp_path / "state"
        monkeypatch.setattr(StateFile, "STATE_DIR", state_dir)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        payload = full_payload(str(tmp_path), session_id=bad_id)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        monkeypatch.setenv("COLUMNS", "200")

        pkg_statusline.main()  # must not raise

        err = capsys.readouterr().err
        assert "Invalid session_id" in err
        assert list(tmp_path.rglob("*evil*")) == []

    @pytest.mark.parametrize("bad_id", NON_STRING_SESSION_IDS)
    def test_validator_raises_valueerror_not_typeerror(self, bad_id):
        from scripts import statusline as sl

        from claude_statusline.core.state import _validate_session_id as core_validate

        for fn in (core_validate, sl._validate_session_id):
            with pytest.raises(ValueError):
                fn(bad_id)


# ---------------------------------------------------------------------------
# Issue #128 / F-BUG-003 — explicit JSON null treated as absent
# ---------------------------------------------------------------------------

NULL_HEAVY_PAYLOAD = {
    "session_id": None,
    "model": None,
    "workspace": {"current_dir": "/tmp/wsnull", "project_dir": None},
    "context_window": None,
    "cost": None,
    "effort": None,
}


class TestNullTolerantExtraction:
    """Payloads with explicit nulls must degrade, not crash (F-BUG-003)."""

    def test_script_null_heavy_payload_renders(self, tmp_path):
        out, code, err = run_script(NULL_HEAVY_PAYLOAD, {"HOME": str(tmp_path)})
        assert code == 0, err
        visible = strip_ansi(out)
        assert "Claude" in visible  # model display_name falls back to default
        assert "wsnull" in visible  # project_dir null -> falls back to current_dir
        assert "%" not in visible  # context_window null -> no context segment

    def test_package_null_heavy_payload_renders(self, tmp_path, monkeypatch, capsys):
        from claude_statusline.cli import statusline as pkg_statusline

        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(NULL_HEAVY_PAYLOAD)))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("COLUMNS", "200")
        pkg_statusline.main()
        out = strip_ansi(capsys.readouterr().out)
        assert "Claude" in out
        assert "wsnull" in out

    def test_null_cost_fields_default_to_zero(self, tmp_path):
        payload = full_payload(str(tmp_path))
        payload["cost"] = {
            "total_cost_usd": None,
            "total_lines_added": None,
            "total_lines_removed": None,
            "total_api_duration_ms": None,
        }
        out, code, _err = run_script(payload, {"HOME": str(tmp_path)})
        assert code == 0
        assert "$0.00" in strip_ansi(out)

    def test_extract_helper_treats_null_as_missing(self):
        from scripts import statusline as sl

        from claude_statusline.cli import statusline as pkg_statusline

        for mod in (sl, pkg_statusline):
            assert mod._extract({"k": None}, "k", "dflt") == "dflt"
            assert mod._extract({}, "k", "dflt") == "dflt"
            assert mod._extract({"k": "v"}, "k", "dflt") == "v"
            assert mod._extract(None, "k", "dflt") == "dflt"
            assert mod._extract("not-a-dict", "k", "dflt") == "dflt"


# ---------------------------------------------------------------------------
# Issue #128 / F-BUG-004 — render catch-all
# ---------------------------------------------------------------------------


class TestRenderCatchAll:
    """Unexpected render exceptions emit a fallback line, traceback to stderr."""

    @pytest.mark.parametrize("script_entry", [True, False])
    def test_raising_segment_produces_fallback(self, tmp_path, monkeypatch, capsys, script_entry):
        boom = RuntimeError("segment exploded")

        if script_entry:
            from scripts import statusline as entry

            monkeypatch.setattr(entry, "get_git_info", lambda *a, **kw: (_ for _ in ()).throw(boom))
        else:
            from claude_statusline.cli import statusline as entry

            monkeypatch.setattr(entry, "get_git_info", lambda *a, **kw: (_ for _ in ()).throw(boom))

        payload = full_payload(str(tmp_path))  # existing dir -> git hook is reached
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        monkeypatch.setenv("HOME", str(tmp_path))

        entry.main()

        captured = capsys.readouterr()
        assert "[Claude] ~" in captured.out
        assert "Traceback" in captured.err
        assert "segment exploded" in captured.err
        assert "Traceback" not in captured.out

    def test_script_invalid_json_still_falls_back(self, tmp_path):
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["HOME"] = str(tmp_path)
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input="{not json",
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "[Claude] ~"


# ---------------------------------------------------------------------------
# Issue #131 / F-SEC-002 — project_dir trust gate
# ---------------------------------------------------------------------------


class TestProjectDirTrustGate:
    """git/gh must only run inside a verified-existing directory (#131)."""

    def test_script_helper_nonexistent_returns_none(self):
        from scripts import statusline as sl

        assert sl._resolve_project_dir("/nonexistent/dir/xyz") is None
        assert sl._resolve_project_dir("") is None
        assert sl._resolve_project_dir(None) is None

    def test_script_helper_existing_resolves(self, tmp_path):
        from scripts import statusline as sl

        assert sl._resolve_project_dir(str(tmp_path)) == str(tmp_path.resolve())

    def test_script_nonexistent_project_dir_skips_git(self, tmp_path, monkeypatch, capsys):
        from scripts import statusline as sl

        calls = []

        def _spy(*a, **kw):
            calls.append(a)
            return ""

        monkeypatch.setattr(sl, "get_git_info", _spy)
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(json.dumps(full_payload("/nonexistent/dir/xyz"))),
        )
        monkeypatch.setenv("HOME", str(tmp_path))
        sl.main()
        capsys.readouterr()
        assert calls == []

    def test_package_nonexistent_project_dir_skips_git_and_pr(self, tmp_path, monkeypatch, capsys):
        from claude_statusline.cli import statusline as pkg

        git_calls, pr_calls = [], []

        monkeypatch.setattr(pkg, "get_git_info", lambda *a, **kw: git_calls.append(a) or "")
        monkeypatch.setattr(pkg, "_get_pr_number", lambda *a, **kw: pr_calls.append(a) or "")
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(json.dumps(full_payload("/nonexistent/dir/xyz"))),
        )
        monkeypatch.setenv("HOME", str(tmp_path))
        pkg.main()
        capsys.readouterr()
        assert git_calls == []
        assert pr_calls == []

    def test_script_existing_project_dir_runs_git(self, tmp_path, monkeypatch, capsys):
        from scripts import statusline as sl

        calls = []
        monkeypatch.setattr(sl, "get_git_info", lambda *a, **kw: calls.append(a) or "")
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(full_payload(str(tmp_path)))))
        monkeypatch.setenv("HOME", str(tmp_path))
        sl.main()
        capsys.readouterr()
        assert len(calls) == 1

    def test_package_existing_project_dir_runs_git(self, tmp_path, monkeypatch, capsys):
        from claude_statusline.cli import statusline as pkg

        calls = []
        monkeypatch.setattr(pkg, "get_git_info", lambda *a, **kw: calls.append(a) or "")
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(full_payload(str(tmp_path)))))
        monkeypatch.setenv("HOME", str(tmp_path))
        pkg.main()
        capsys.readouterr()
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Issue #131 / F-SEC-003 — state files created 0600
# ---------------------------------------------------------------------------


def assert_owner_only_mode(path: Path) -> None:
    """Assert 0600 where POSIX modes exist; strongest claim available elsewhere."""
    mode = stat.S_IMODE(path.stat().st_mode)
    if sys.platform == "win32":
        # NTFS reports 0o666 regardless of creation mode; assert the owner
        # read/write bits, which is the strongest meaningful check there.
        assert mode & 0o600 == 0o600
    else:
        assert mode == 0o600


class TestStateFilePermissions:
    """Newly created state files must be owner-only 0600 (#131)."""

    def test_package_append_entry_creates_0600(self, tmp_path, monkeypatch):
        from claude_statusline.core.state import StateEntry, StateFile

        monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path)
        monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
        (tmp_path / "old").mkdir()

        sf = StateFile("perm-check")
        entry = StateEntry(
            timestamp=1710288000,
            total_input_tokens=100,
            total_output_tokens=200,
            current_input_tokens=300,
            current_output_tokens=400,
            cache_creation=500,
            cache_read=600,
            cost_usd=0.01,
            lines_added=10,
            lines_removed=5,
            session_id="perm-check",
            model_id="model",
            workspace_project_dir="/tmp/proj",
            context_window_size=200000,
        )
        sf.append_entry(entry)

        assert_owner_only_mode(sf.file_path)

    def test_script_state_write_creates_0600(self, tmp_path):
        payload = full_payload(str(tmp_path), session_id="perm-script")
        _out, code, err = run_script(payload, {"HOME": str(tmp_path)})
        assert code == 0, err
        state_file = tmp_path / ".claude" / "statusline" / "statusline.perm-script.state"
        assert state_file.exists()
        assert_owner_only_mode(state_file)


# ---------------------------------------------------------------------------
# Parity guards — synced logic must stay identical in both copies
# ---------------------------------------------------------------------------


def _body_ast(fn):
    """AST-dump a function's body minus docstring/signature annotations."""
    source = textwrap.dedent(inspect.getsource(fn))
    fn_def = ast.parse(source).body[0]
    body = fn_def.body[1:]  # drop docstring
    return ast.dump(ast.Module(body=body, type_ignores=[]))


class TestSyncParity:
    """Identical-source guarantees for the newly synced helpers."""

    def test_session_id_validation_identical_in_both_copies(self):
        from scripts import statusline as sl

        from claude_statusline.core.state import _validate_session_id as core_validate

        assert _body_ast(core_validate) == _body_ast(sl._validate_session_id)

    def test_extract_helper_identical_in_both_copies(self):
        from scripts import statusline as sl

        from claude_statusline.cli import statusline as pkg_statusline

        assert _body_ast(sl._extract) == _body_ast(pkg_statusline._extract)
