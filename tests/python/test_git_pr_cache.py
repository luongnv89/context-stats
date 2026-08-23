"""Tests for _get_pr_number, its TTL caches, and git failure branches
(issue #138, F-TEST-003).

gh/git subprocesses are stubbed via monkeypatched subprocess.run; the cache
file lives under tmp_path; time.time is frozen per-test for TTL boundaries.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from claude_statusline.core import git as git_mod
from claude_statusline.core.git import (
    _PR_CACHE_NEGATIVE_TTL_SECONDS,
    _PR_CACHE_TTL_SECONDS,
    _get_pr_number,
    _pr_cache_get,
    _pr_cache_set,
    get_git_info,
)


@pytest.fixture()
def cache_file(tmp_path, monkeypatch):
    """Redirect the shared PR cache into tmp_path."""
    path = tmp_path / "statusline" / "pr_number_cache.json"
    monkeypatch.setattr(git_mod, "_pr_cache_file", lambda: path)
    return path


@pytest.fixture()
def fake_gh(monkeypatch):
    """Make shutil.which('gh') report an available gh binary."""

    def _enable(path="/usr/bin/gh"):
        monkeypatch.setattr(git_mod.shutil, "which", lambda name: path if name == "gh" else None)

    return _enable


class StubCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# _pr_cache_get / _pr_cache_set — low-level cache behaviour
# ---------------------------------------------------------------------------


class TestPrCache:
    def test_missing_file_is_a_miss(self, cache_file):
        assert _pr_cache_get("k") is None

    def test_corrupt_json_is_a_miss(self, cache_file):
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("{not json")
        assert _pr_cache_get("k") is None

    def test_non_dict_payload_is_a_miss(self, cache_file):
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(json.dumps(["a", "b"]))
        assert _pr_cache_get("k") is None

    def test_unexpired_entry_hit(self, cache_file, monkeypatch):
        monkeypatch.setattr(git_mod.time, "time", lambda: 1000.0)
        _pr_cache_set("k", "#7", ttl=30)
        assert _pr_cache_get("k") == "#7"

    def test_expired_entry_miss_at_boundary(self, cache_file, monkeypatch):
        """exp == now is a miss (hit requires exp strictly > now)."""
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(json.dumps({"k": {"pr": "#7", "exp": 1000}}))
        monkeypatch.setattr(git_mod.time, "time", lambda: 1000.0)
        assert _pr_cache_get("k") is None

    def test_just_before_expiry_hit(self, cache_file, monkeypatch):
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(json.dumps({"k": {"pr": "#7", "exp": 1000}}))
        monkeypatch.setattr(git_mod.time, "time", lambda: 999.9)
        assert _pr_cache_get("k") == "#7"

    def test_set_prunes_expired_entries(self, cache_file, monkeypatch):
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(
            json.dumps({"old": {"pr": "#1", "exp": 10}, "live": {"pr": "#2", "exp": 10_000}})
        )
        monkeypatch.setattr(git_mod.time, "time", lambda: 100.0)
        _pr_cache_set("new", "#3")
        data = json.loads(cache_file.read_text())
        assert "old" not in data
        assert data["live"]["pr"] == "#2"
        assert data["new"]["pr"] == "#3"

    def test_default_ttl_used_when_none_given(self, cache_file, monkeypatch):
        monkeypatch.setattr(git_mod.time, "time", lambda: 500.0)
        _pr_cache_set("k", "#9")
        data = json.loads(cache_file.read_text())
        assert data["k"]["exp"] == pytest.approx(500.0 + _PR_CACHE_TTL_SECONDS)

    def test_non_dict_entry_values_pruned(self, cache_file, monkeypatch):
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(json.dumps({"junk": "not-a-dict"}))
        monkeypatch.setattr(git_mod.time, "time", lambda: 100.0)
        _pr_cache_set("k", "#1")
        data = json.loads(cache_file.read_text())
        assert "junk" not in data
        assert data["k"] == {"pr": "#1", "exp": 100.0 + _PR_CACHE_TTL_SECONDS}

    def test_unwritable_cache_dir_swallows_error(self, tmp_path, monkeypatch):
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file")

        def boom():
            return blocker / "child" / "cache.json"

        monkeypatch.setattr(git_mod, "_pr_cache_file", boom)
        _pr_cache_set("k", "#1")  # must not raise
        assert _pr_cache_get("k") is None

    def test_replace_failure_cleans_temp_and_swallows(self, cache_file, monkeypatch):
        cache_file.parent.mkdir(parents=True)

        def fail_replace(src, dst):
            raise OSError("replace denied")

        monkeypatch.setattr(git_mod.os, "replace", fail_replace)
        _pr_cache_set("k", "#1")  # swallowed
        leftovers = list(cache_file.parent.glob("*.tmp"))
        assert leftovers == []


# ---------------------------------------------------------------------------
# _get_pr_number — lookup flows against stubbed gh/git
# ---------------------------------------------------------------------------


class TestGetPrNumber:
    def test_gh_absent_returns_empty_without_subprocess(self, cache_file, monkeypatch):
        monkeypatch.setattr(git_mod.shutil, "which", lambda name: None)
        called = False

        def guard(*a, **k):
            nonlocal called
            called = True
            return StubCompleted()

        monkeypatch.setattr(git_mod.subprocess, "run", guard)
        assert _get_pr_number(Path("/proj")) == ""
        assert called is False

    def _stub_runs(self, monkeypatch, runs):
        """Patch subprocess.run to pop scripted results in order."""
        scripted = list(runs)
        calls = []

        def runner(argv, **kwargs):
            calls.append(list(argv))
            if not scripted:
                raise AssertionError("unexpected extra subprocess.run call")
            return scripted.pop(0)

        monkeypatch.setattr(git_mod.subprocess, "run", runner)
        return calls

    def test_branch_lookup_failure_returns_empty(self, cache_file, fake_gh, monkeypatch):
        self._stub_runs(monkeypatch, [StubCompleted(returncode=1)])
        assert _get_pr_number(Path("/proj")) == ""

    def test_empty_branch_name_returns_empty(self, cache_file, fake_gh, monkeypatch):
        self._stub_runs(monkeypatch, [StubCompleted(stdout="\n")])
        assert _get_pr_number(Path("/proj")) == ""

    def test_pr_found_formats_hash_prefix_and_caches_positive(
        self, cache_file, fake_gh, monkeypatch
    ):
        calls = self._stub_runs(
            monkeypatch,
            [
                StubCompleted(stdout="feature\n"),
                StubCompleted(stdout='[{"number": 42}]'),
                StubCompleted(stdout="feature\n"),  # branch re-resolved on 2nd call
            ],
        )
        monkeypatch.setattr(git_mod.time, "time", lambda: 100.0)
        assert _get_pr_number(Path("/proj")) == "#42"
        # gh was invoked exactly once; second call served from cache.
        cached = json.loads(cache_file.read_text())
        key = next(iter(cached))
        assert "/proj" in key and "feature" in key
        assert cached[key]["pr"] == "#42"
        assert cached[key]["exp"] == pytest.approx(100.0 + _PR_CACHE_TTL_SECONDS)
        assert sum(1 for c in calls if c[0] == "gh") == 1
        assert _get_pr_number(Path("/proj")) == "#42"
        assert sum(1 for c in calls if c[0] == "gh") == 1

    def test_no_open_pr_caches_empty_positive(self, cache_file, fake_gh, monkeypatch):
        self._stub_runs(
            monkeypatch,
            [
                StubCompleted(stdout="main\n"),
                StubCompleted(stdout="[]"),
            ],
        )
        monkeypatch.setattr(git_mod.time, "time", lambda: 100.0)
        assert _get_pr_number(Path("/proj")) == ""
        data = json.loads(cache_file.read_text())
        entry = next(iter(data.values()))
        assert entry["pr"] == ""
        assert entry["exp"] == pytest.approx(100.0 + _PR_CACHE_TTL_SECONDS)

    def test_malformed_gh_output_negatively_cached(self, cache_file, fake_gh, monkeypatch):
        self._stub_runs(
            monkeypatch,
            [
                StubCompleted(stdout="dev\n"),
                StubCompleted(stdout="<html>oops"),
            ],
        )
        monkeypatch.setattr(git_mod.time, "time", lambda: 100.0)
        assert _get_pr_number(Path("/proj")) == ""
        entry = next(iter(json.loads(cache_file.read_text()).values()))
        assert entry["pr"] == ""
        assert entry["exp"] == pytest.approx(100.0 + _PR_CACHE_NEGATIVE_TTL_SECONDS)

    def test_gh_failure_negatively_cached_then_recovered_after_expiry(
        self, cache_file, fake_gh, monkeypatch
    ):
        clock = {"now": 100.0}
        monkeypatch.setattr(git_mod.time, "time", lambda: clock["now"])
        self._stub_runs(
            monkeypatch,
            [
                StubCompleted(stdout="dev\n"),
                StubCompleted(returncode=1, stderr="auth expired"),
                StubCompleted(stdout="dev\n"),  # 2nd call: branch re-resolved, negative hit
                StubCompleted(stdout="dev\n"),  # 3rd call after expiry: branch again
                StubCompleted(stdout='[{"number": 5}]'),
            ],
        )
        assert _get_pr_number(Path("/proj")) == ""  # failure, negative-cached
        assert _get_pr_number(Path("/proj")) == ""  # still inside negative TTL
        clock["now"] += _PR_CACHE_NEGATIVE_TTL_SECONDS + 1  # expire the negative entry
        assert _get_pr_number(Path("/proj")) == "#5"

    def test_branch_timeout_negatively_cached_when_key_known(self, cache_file, fake_gh, monkeypatch):
        """Timeout on the *gh* leg (branch already resolved) → negative cache."""
        def runner(argv, **kwargs):
            if argv[0] == "git":
                return StubCompleted(stdout="dev\n")
            raise subprocess.TimeoutExpired(cmd="gh", timeout=5)

        monkeypatch.setattr(git_mod.subprocess, "run", runner)
        monkeypatch.setattr(git_mod.time, "time", lambda: 100.0)
        assert _get_pr_number(Path("/proj")) == ""
        entry = next(iter(json.loads(cache_file.read_text()).values()))
        assert entry["exp"] == pytest.approx(100.0 + _PR_CACHE_NEGATIVE_TTL_SECONDS)

    def test_branch_timeout_before_key_leaves_no_cache(self, cache_file, fake_gh, monkeypatch):
        def runner(*a, **k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=5)

        monkeypatch.setattr(git_mod.subprocess, "run", runner)
        assert _get_pr_number(Path("/proj")) == ""
        assert not cache_file.exists()

    def test_oserror_on_gh_negatively_cached(self, cache_file, fake_gh, monkeypatch):
        def runner(argv, **kwargs):
            if argv[0] == "git":
                return StubCompleted(stdout="dev\n")
            raise OSError("spawn failed")

        monkeypatch.setattr(git_mod.subprocess, "run", runner)
        monkeypatch.setattr(git_mod.time, "time", lambda: 100.0)
        assert _get_pr_number(Path("/proj")) == ""
        assert cache_file.exists()


# ---------------------------------------------------------------------------
# get_git_info — failure branches and formatting variants
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path):
    """A real git repo with one commit and one untracked change."""
    import subprocess as sp

    workdir = tmp_path / "repo"
    workdir.mkdir()
    env_vars = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    import os

    env = {**os.environ, **env_vars}
    sp.run(["git", "init", "-q"], cwd=workdir, check=True, env=env)
    (workdir / "tracked.txt").write_text("hello\n")
    sp.run(["git", "add", "."], cwd=workdir, check=True, env=env)
    sp.run(["git", "commit", "-qm", "init"], cwd=workdir, check=True, env=env)
    return workdir


class TestGetGitInfo:
    def test_not_a_repo_returns_empty(self, tmp_path):
        empty = tmp_path / "plain"
        empty.mkdir()
        assert get_git_info(empty) == ""

    def test_real_repo_clean_shows_branch_only(self, repo):
        out = get_git_info(repo, colors_enabled=False)
        assert out.startswith(" | ")
        assert "[" not in out

    def test_real_repo_dirty_shows_change_count(self, repo):
        (repo / "tracked.txt").write_text("changed\n")
        (repo / "new.txt").write_text("x\n")
        out = get_git_info(repo, colors_enabled=False)
        assert "[2]" in out

    def test_color_manager_overrides_constants(self, repo):
        from claude_statusline.core.colors import ColorManager

        cm = ColorManager(enabled=True)
        plain = get_git_info(repo, colors_enabled=False)
        colored = get_git_info(repo, colors_enabled=False, color_manager=cm)
        # Manager colors are applied even when the legacy flag says "off".
        assert "\033[" in colored
        if "\033[" not in plain:
            assert colored != plain

    def test_rev_parse_failure_returns_empty(self, repo, monkeypatch):
        monkeypatch.setattr(
            git_mod.subprocess,
            "run",
            lambda *a, **k: StubCompleted(returncode=128),
        )
        assert get_git_info(repo) == ""

    def test_empty_branch_name_returns_empty(self, repo, monkeypatch):
        monkeypatch.setattr(
            git_mod.subprocess,
            "run",
            lambda *a, **k: StubCompleted(stdout="\n"),
        )
        assert get_git_info(repo) == ""

    def test_status_failure_counts_zero_changes(self, repo, monkeypatch):
        def runner(argv, **kwargs):
            if "status" in argv:
                return StubCompleted(returncode=128)
            return StubCompleted(stdout="main\n")

        monkeypatch.setattr(git_mod.subprocess, "run", runner)
        out = get_git_info(repo, colors_enabled=False)
        assert "main" in out
        assert "[" not in out

    def test_timeout_degrades_to_empty(self, repo, monkeypatch):
        def runner(*a, **k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=5)

        monkeypatch.setattr(git_mod.subprocess, "run", runner)
        assert get_git_info(repo) == ""

    def test_oserror_degrades_to_empty(self, repo, monkeypatch):
        def runner(*a, **k):
            raise OSError("no git binary")

        monkeypatch.setattr(git_mod.subprocess, "run", runner)
        assert get_git_info(repo) == ""

    def test_worktree_style_git_file_accepted(self, repo, tmp_path):
        """``.git`` as a pointer file (worktree/submodule) is still probed."""
        linked = tmp_path / "wt"
        linked.mkdir()
        (linked / ".git").write_text("gitdir: /nonexistent\n")
        # git commands fail cleanly → empty string, no crash (F-BUG-007).
        assert get_git_info(linked, colors_enabled=False) == ""
