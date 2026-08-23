"""State-file robustness tests for issues #129/#130 (F-BUG-005..008).

Covers: legacy-migration OSError guards (005), CSV string-field validation
(006), worktree-style `.git` files (007), and find_latest/rotation race
guards (008) — asserted on BOTH the package (`claude_statusline.core.state`)
and the standalone script (`scripts/statusline.py`) where mirrored.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_statusline.core.state import (
    StateEntry,
    StateFile,
    _csv_unsafe_reason,
    _sanitize_workspace_dir,
    _validate_csv_field,
    _validate_session_id,
)

SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "statusline.py"


@pytest.fixture()
def sl_module():
    """Import the standalone statusline as a module."""
    from scripts import statusline as sl

    return sl


@pytest.fixture()
def state_dirs(tmp_path, monkeypatch):
    """Isolate both copies' state dirs under tmp_path."""
    monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
    (tmp_path / "old").mkdir()
    return tmp_path


def _make_entry(**overrides) -> StateEntry:
    defaults: dict = {
        "timestamp": 1710288000,
        "total_input_tokens": 100,
        "total_output_tokens": 200,
        "current_input_tokens": 300,
        "current_output_tokens": 400,
        "cache_creation": 500,
        "cache_read": 600,
        "cost_usd": 0.01,
        "lines_added": 10,
        "lines_removed": 5,
        "session_id": "sess-1",
        "model_id": "claude-test",
        "workspace_project_dir": "/tmp/proj",
        "context_window_size": 200000,
        "api_duration_ms": 1500,
    }
    defaults.update(overrides)
    return StateEntry(**defaults)


# ---------------------------------------------------------------------------
# F-BUG-005 — legacy-state migration must never break the refresh
# ---------------------------------------------------------------------------


class TestMigrationOSErrorGuards:
    def test_package_move_failure_warns_and_continues(self, state_dirs, capsys):
        old_file = StateFile.OLD_STATE_DIR / "statusline.old.state"
        old_file.write_text("1710288000,100\n")

        with patch("claude_statusline.core.state.shutil.move", side_effect=OSError("denied")):
            sf = StateFile("fresh")  # constructor runs migration; must not raise

        assert sf is not None
        assert old_file.exists()  # left in place for a later pass
        assert "failed to migrate legacy state file" in capsys.readouterr().err

    def test_package_remove_failure_warns_and_continues(self, state_dirs, capsys):
        old_file = StateFile.OLD_STATE_DIR / "statusline.dup.state"
        old_file.write_text("1710288000,100\n")
        # Same name already in the new dir → migration takes the unlink path.
        StateFile.STATE_DIR.mkdir(parents=True, exist_ok=True)
        (StateFile.STATE_DIR / "statusline.dup.state").write_text("1,2\n")

        with patch("pathlib.Path.unlink", side_effect=OSError("busy")):
            StateFile("fresh")  # must not raise
        assert "failed to migrate legacy state file" in capsys.readouterr().err

    def test_standalone_move_failure_warns_and_continues(self, tmp_path, sl_module, capsys):
        state_dir = tmp_path / "state"
        old_dir = tmp_path / "old"
        state_dir.mkdir()
        old_dir.mkdir()
        old_file = old_dir / "statusline.legacy.state"
        old_file.write_text("1710288000,100\n")

        with patch.object(sl_module.shutil, "move", side_effect=OSError("denied")):
            sl_module._migrate_legacy_state_files(str(state_dir), str(old_dir))

        assert old_file.exists()  # untouched after failed move
        err = capsys.readouterr().err
        assert "failed to migrate legacy state file" in err
        assert "statusline.legacy.state" in err

    def test_standalone_remove_failure_warns_and_continues(self, tmp_path, sl_module, capsys):
        state_dir = tmp_path / "state"
        old_dir = tmp_path / "old"
        state_dir.mkdir()
        old_dir.mkdir()
        old_file = old_dir / "statusline.dup.state"
        old_file.write_text("1710288000,100\n")
        (state_dir / "statusline.dup.state").write_text("1,2\n")  # triggers remove branch

        with patch.object(sl_module.os, "remove", side_effect=OSError("busy")):
            sl_module._migrate_legacy_state_files(str(state_dir), str(old_dir))  # no raise

        assert old_file.exists()
        assert "failed to migrate legacy state file" in capsys.readouterr().err

    def test_standalone_migration_success_still_moves(self, tmp_path, sl_module):
        state_dir = tmp_path / "state"
        old_dir = tmp_path / "old"
        state_dir.mkdir()
        old_dir.mkdir()
        old_file = old_dir / "statusline.movable.state"
        old_file.write_text("1710288000,100\n")

        sl_module._migrate_legacy_state_files(str(state_dir), str(old_dir))

        assert not old_file.exists()
        assert (state_dir / "statusline.movable.state").exists()

    def test_parity_same_warning_text(self, state_dirs, sl_module, capsys):
        """Both copies warn with the same message shape."""
        old_file = StateFile.OLD_STATE_DIR / "statusline.parity.state"
        old_file.write_text("1,2\n")
        with patch("claude_statusline.core.state.shutil.move", side_effect=OSError("x")):
            StateFile("p")
        pkg_err = capsys.readouterr().err.strip()

        sd, od = state_dirs / "sd", state_dirs / "od"
        sd.mkdir(exist_ok=True)
        od.mkdir(exist_ok=True)
        of = od / "statusline.parity.state"
        of.write_text("1,2\n")
        with patch.object(sl_module.shutil, "move", side_effect=OSError("x")):
            sl_module._migrate_legacy_state_files(str(sd), str(od))
        sl_err = capsys.readouterr().err.strip()

        assert "failed to migrate legacy state file" in pkg_err
        assert "failed to migrate legacy state file" in sl_err


# ---------------------------------------------------------------------------
# F-BUG-006 — CSV string-field validation (comma/newline/control chars)
# ---------------------------------------------------------------------------

CSV_UNSAFE_VALUES = [
    "a,b",  # comma shifts column indexes
    "a\nb",  # newline forges a row boundary
    "a\rb",
    "a\tb",  # control char
    "a\x1bb",  # escape
    "a\x7fb",  # DEL
]


class TestCsvFieldValidation:
    @pytest.mark.parametrize("bad", CSV_UNSAFE_VALUES)
    def test_validate_session_id_rejects_csv_unsafe(self, bad):
        with pytest.raises(ValueError, match="Invalid session_id"):
            _validate_session_id(bad)

    @pytest.mark.parametrize("bad", CSV_UNSAFE_VALUES)
    def test_script_validate_session_id_rejects_csv_unsafe(self, bad, sl_module):
        with pytest.raises(ValueError, match="Invalid session_id"):
            sl_module._validate_session_id(bad)

    @pytest.mark.parametrize("bad", CSV_UNSAFE_VALUES)
    def test_validate_csv_field_rejects_unsafe(self, bad):
        with pytest.raises(ValueError, match="Invalid model_id"):
            _validate_csv_field("model_id", bad)

    def test_validate_csv_field_non_string(self):
        with pytest.raises(ValueError, match="expected str"):
            _validate_csv_field("session_id", 12345)

    def test_safe_values_pass_both_copies(self, sl_module):
        for fn in (_validate_session_id, sl_module._validate_session_id):
            fn("abc-123_DEF")  # should not raise
        assert _csv_unsafe_reason("safe-value_123") is None
        assert sl_module._csv_unsafe_reason("safe-value_123") is None

    def test_to_csv_line_raises_on_bad_model_id(self):
        entry = _make_entry(model_id="opus,model")
        with pytest.raises(ValueError, match="Invalid model_id"):
            entry.to_csv_line()

    def test_to_csv_line_raises_on_bad_session_id(self):
        entry = _make_entry(session_id="sess\nid")
        with pytest.raises(ValueError, match="Invalid session_id"):
            entry.to_csv_line()

    def test_append_entry_refuses_bad_fields_without_writing(self, state_dirs, capsys):
        sf = StateFile("guarded")
        entry = _make_entry(model_id="bad,model")
        sf.append_entry(entry)  # warns instead of writing/crashing

        assert not sf.file_path.exists()  # nothing written
        err = capsys.readouterr().err
        assert "refusing to write state" in err
        assert "Invalid model_id" in err

    def test_append_entry_accepts_good_fields(self, state_dirs):
        sf = StateFile("good")
        sf.append_entry(_make_entry())
        lines = sf.file_path.read_text().splitlines()
        assert len(lines) == 1
        assert len(lines[0].split(",")) == 15  # column indexes intact

    def test_workspace_dir_control_chars_sanitized(self):
        assert _sanitize_workspace_dir("/tmp/a,b") == "/tmp/a_b"
        assert _sanitize_workspace_dir("/tmp/a\nb\tc\x7f") == "/tmp/a_b_c_"

    def test_sanitize_helpers_identical_output(self, sl_module):
        samples = ["/home/u/proj,inc", "weird\rdir\n", "", "plain"]
        for s in samples:
            assert _sanitize_workspace_dir(s) == sl_module._sanitize_workspace_dir(s)


# ---------------------------------------------------------------------------
# F-BUG-007 — worktree/submodule `.git` files keep git info rendering
# ---------------------------------------------------------------------------


class FakeCompleted:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


class TestWorktreeGitFile:
    def _worktree_style_repo(self, root: Path) -> Path:
        """A checkout whose .git is a FILE pointing elsewhere (worktree style)."""
        real_gitdir = root / "real-gitdir"
        real_gitdir.mkdir()
        worktree = root / "wt"
        worktree.mkdir()
        (worktree / ".git").write_text(f"gitdir: {real_gitdir}\n")
        return worktree

    def test_package_git_info_with_git_file(self, tmp_path, monkeypatch):
        import claude_statusline._shared as shared
        from claude_statusline.core import git as core_git

        wt = self._worktree_style_repo(tmp_path)

        def fake_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                return FakeCompleted("wt-branch\n")
            return FakeCompleted(" M file.py\n?? new.py\n")

        # F-PERF-003: the change count is a separate capped streaming call;
        # stub its result so this test stays focused on the .git-file path.
        monkeypatch.setattr(shared, "_count_changes_capped", lambda d, cap=None: (2, False))
        with patch.object(core_git.subprocess, "run", side_effect=fake_run):
            info = core_git.get_git_info(wt)
        assert "wt-branch" in info
        assert "[2]" in info

    def test_script_git_info_with_git_file(self, tmp_path, sl_module, monkeypatch):
        import claude_statusline._shared as shared

        wt = self._worktree_style_repo(tmp_path)

        def fake_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                return FakeCompleted("wt-branch\n")
            return FakeCompleted(" M file.py\n")

        monkeypatch.setattr(shared, "_count_changes_capped", lambda d, cap=None: (1, False))
        with patch.object(sl_module.subprocess, "run", side_effect=fake_run):
            info = sl_module.get_git_info(str(wt))
        assert "wt-branch" in info
        assert "[1]" in info

    def test_missing_git_still_empty(self, tmp_path):
        from claude_statusline.core import git as core_git

        plain = tmp_path / "plain"
        plain.mkdir()
        assert core_git.get_git_info(plain) == ""

    def test_bogus_git_file_degrades_to_empty(self, tmp_path):
        """A non-repo `.git` file fails cleanly via git's own exit code."""
        from claude_statusline.core import git as core_git

        bogus = tmp_path / "bogus"
        bogus.mkdir()
        (bogus / ".git").write_text("gitdir: /nonexistent\n")
        assert core_git.get_git_info(bogus) == ""

    @pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
    def test_real_worktree_integration(self, tmp_path):
        """End-to-end: `git worktree add` produces a .git FILE; info renders."""
        origin = tmp_path / "origin"
        origin.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }

        def git(*args, cwd=None):
            return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)

        assert git("init", "-q", "-b", "main", str(origin)).returncode == 0
        (origin / "f.txt").write_text("x\n")
        git("add", ".", cwd=str(origin))
        git("commit", "-qm", "init", cwd=str(origin))

        wt = tmp_path / "linked-wt"
        assert (
            git("worktree", "add", "-b", "feature-wt", str(wt), "main", cwd=str(origin)).returncode
            == 0
        )
        (wt / "g.txt").write_text("y\n")

        from claude_statusline.core import git as core_git

        info = core_git.get_git_info(wt)
        assert "feature-wt" in info
        assert "[1]" in info  # untracked g.txt counted as a change


# ---------------------------------------------------------------------------
# F-BUG-008 — TOCTOU guards + locked rotation
# ---------------------------------------------------------------------------


class TestFindLatestRaceGuards:
    def test_vanished_file_skipped(self, state_dirs, monkeypatch):
        sf = StateFile(None)
        keep = StateFile.STATE_DIR / "statusline.keep.state"
        keep.write_text("1,2\n")
        gone = StateFile.STATE_DIR / "statusline.gone.state"
        gone.write_text("3,4\n")
        # Make 'gone' the newest so it would win without the guard...
        past = keep.stat().st_mtime - 10
        os.utime(keep, (past, past))

        real_stat = Path.stat

        def flaky_stat(self, *args, **kwargs):
            if self.name == "statusline.gone.state":
                raise FileNotFoundError("vanished mid-scan")
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", flaky_stat)
        result = sf.find_latest_state_file()
        assert result is not None
        assert result.name == "statusline.keep.state"

    def test_candidate_stats_failing_falls_back_to_default(self, state_dirs, monkeypatch):
        """When every globbed candidate vanishes mid-scan, use the default file."""
        sf = StateFile(None)
        default = StateFile.STATE_DIR / "statusline.state"
        default.write_text("1,2\n")
        (StateFile.STATE_DIR / "statusline.other.state").write_text("3,4\n")

        real_stat = Path.stat

        def flaky_stat(self, *args, **kwargs):
            if self.name == "statusline.other.state":
                raise FileNotFoundError("vanished mid-scan")
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", flaky_stat)
        # The only glob candidate failed its stat → falls back to default.
        result = sf.find_latest_state_file()
        assert result is not None
        assert result.name == "statusline.state"


class TestLockedRotation:
    def test_append_rotation_under_lock_keeps_newest_line(self, state_dirs):
        """Rotation triggered by append_entry retains the just-appended row."""
        sf = StateFile("lockrot")
        lines = [
            f"{1710288000 + i},100,200,300,400,500,600,0.01,10,5,s{i},m,/p,200000\n"
            for i in range(10_000)
        ]
        sf.file_path.write_text("".join(lines))
        sf.append_entry(_make_entry(timestamp=1719999999))
        result = sf.file_path.read_text().splitlines()
        assert len(result) == 5_000
        assert "1719999999" in result[-1]

    def test_append_rotate_works_without_fcntl(self, state_dirs, monkeypatch):
        """Platforms without fcntl degrade to the unlocked atomic-rename path."""
        from claude_statusline.core import state as state_mod

        monkeypatch.setattr(state_mod, "fcntl", None)
        sf = StateFile("nofcntl")
        lines = ["x,y\n"] * 10_001
        sf.file_path.write_text("".join(lines))
        sf.append_entry(_make_entry())
        result = sf.file_path.read_text().splitlines()
        assert len(result) == 5_000

    def test_direct_maybe_rotate_still_rotates(self, state_dirs):
        sf = StateFile("direct")
        sf.file_path.write_text("".join("x,y\n" for _ in range(10_001)))
        sf._maybe_rotate()
        assert len(sf.file_path.read_text().splitlines()) == 5_000

    def test_script_maybe_rotate_locked_wrapper(self, tmp_path, sl_module):
        target = tmp_path / "script.state"
        target.write_text("".join("x,y\n" for _ in range(10_001)))
        sl_module.maybe_rotate_state_file(str(target))
        assert len(target.read_text().splitlines()) == 5_000
        assert not list(tmp_path.glob("*.tmp"))

    def test_lock_helpers_are_noop_when_fcntl_missing(self, state_dirs, monkeypatch):
        from claude_statusline.core import state as state_mod

        monkeypatch.setattr(state_mod, "fcntl", None)
        StateFile.STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(StateFile.STATE_DIR / "probe.state", "w") as fh:  # noqa: SIM115
            state_mod._lock_state_file(fh)  # must not raise
            state_mod._unlock_state_file(fh)

    def test_append_write_mode_preserves_content(self, state_dirs):
        """Switching O_WRONLY→O_RDWR|O_APPEND must not truncate existing rows."""
        sf = StateFile("appendmode")
        sf.append_entry(_make_entry(timestamp=111))
        sf.append_entry(_make_entry(timestamp=222))
        lines = sf.file_path.read_text().splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("111")
        assert lines[1].startswith("222")


# ---------------------------------------------------------------------------
# Contract sanity — standalone write path rejects CSV-unsafe model_id
# ---------------------------------------------------------------------------


class TestStandaloneWriteSiteGuard:
    SL_STATE_DIR = "~/.claude/statusline"

    def test_render_refuses_model_id_with_comma(self, tmp_path, monkeypatch):
        """Full-pipeline: unsafe model.id → warning, no state file written."""
        payload = {
            "session_id": "site-guard",
            "model": {"id": "bad,model", "display_name": "Test"},
            "workspace": {"current_dir": str(tmp_path), "project_dir": str(tmp_path)},
            "context_window": {
                "context_window_size": 200000,
                "total_input_tokens": 1000,
                "total_output_tokens": 500,
                "current_usage": {
                    "input_tokens": 10000,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 200,
                    "output_tokens": 900,
                },
            },
            "cost": {"total_cost_usd": 0.42},
        }
        home = tmp_path / "home"
        home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert result.returncode == 0
        assert "refusing to write state file" in result.stderr
        state_file = home / ".claude" / "statusline" / "statusline.site-guard.state"
        assert not state_file.exists()

    def test_render_sanitizes_workspace_dir_in_written_row(self, tmp_path):
        """Comma-bearing project dirs are sanitized before hitting the CSV."""
        home = tmp_path / "home"
        proj = tmp_path / "proj,withcomma"  # comma in the directory name itself
        proj.mkdir()
        payload = {
            "session_id": "sanitized-row",
            "model": {"id": "claude-test", "display_name": "Test"},
            "workspace": {"current_dir": str(proj), "project_dir": str(proj)},
            "context_window": {
                "context_window_size": 200000,
                "current_usage": {
                    "input_tokens": 10000,
                    "cache_creation_input_tokens": 500,
                    "cache_read_input_tokens": 200,
                    "output_tokens": 900,
                },
            },
        }
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        state_file = home / ".claude" / "statusline" / "statusline.sanitized-row.state"
        assert state_file.exists()
        parts = state_file.read_text().splitlines()[0].split(",")
        assert len(parts) == 15  # commas in dir did not shift columns
        assert "," not in parts[12]
        assert "_" in parts[12]
