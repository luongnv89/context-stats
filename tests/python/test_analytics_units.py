"""Direct unit tests for the analytics engine and state recovery paths
(issue #139, F-TEST-004/F-TEST-005).

Analytics: malformed CSV rows, empty/unreadable files, multi-project
grouping, date filtering, aggregation math. State: tmp_path fault-injection
for IO-failure recovery branches not already covered by
test_state_robustness.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_statusline.analytics import (
    ProjectStats,
    SessionStats,
    _discover_state_files,
    _group_sessions_by_project,
    _load_session_stats,
    load_all_projects,
)
from claude_statusline.core.state import StateEntry, StateFile


@pytest.fixture()
def state_dirs(tmp_path, monkeypatch):
    """Isolate both state dirs under tmp_path."""
    monkeypatch.setattr(StateFile, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(StateFile, "OLD_STATE_DIR", tmp_path / "old")
    return tmp_path


def _csv_line(ts=1000, sid="s1", model="claude-opus", proj="/home/user/proj", **kw) -> str:
    defaults: dict = {
        "total_input_tokens": 1000,
        "total_output_tokens": 200,
        "current_input_tokens": 300,
        "current_output_tokens": 50,
        "cache_creation": 100,
        "cache_read": 40,
        "cost_usd": 0.05,
        "lines_added": 10,
        "lines_removed": 2,
        "context_window_size": 200000,
        "api_duration_ms": 1200,
    }
    defaults.update(kw)
    e = StateEntry(
        timestamp=ts,
        session_id=sid,
        model_id=model,
        workspace_project_dir=proj,
        **defaults,
    )
    return e.to_csv_line()


def _session(sid="s1", proj="/p", start=1000, end=2000, cost=1.0, tin=100, tout=50, cc=10, cr=5):
    s = SessionStats(
        session_id=sid,
        project_dir=proj,
        model_id="claude-opus",
        total_input_tokens=tin,
        total_output_tokens=tout,
        total_cache_creation=cc,
        total_cache_read=cr,
        cost_usd=cost,
        start_time=start,
        end_time=end,
        entry_count=3,
    )
    return s


# ---------------------------------------------------------------------------
# SessionStats / ProjectStats value objects
# ---------------------------------------------------------------------------


class TestSessionStats:
    def test_total_tokens_sums_all_buckets(self):
        s = _session(tin=100, tout=50, cc=10, cr=5)
        assert s.total_tokens() == 165

    def test_cache_hit_ratio_zero_total_guard(self):
        s = _session(tin=0, tout=0, cc=0, cr=0)
        assert s.cache_hit_ratio() == 0.0

    def test_cache_hit_ratio_percentage(self):
        s = _session(tin=0, tout=0, cc=30, cr=30)
        assert s.cache_hit_ratio() == pytest.approx(50.0)

    @pytest.mark.parametrize(
        "model_id,family",
        [
            ("claude-opus-4-6", "opus"),
            ("OPUS-thing", "opus"),
            ("claude-sonnet-4", "sonnet"),
            ("claude-haiku-latest", "haiku"),
            ("something-else", "other"),
            ("", "other"),
        ],
    )
    def test_model_family_branches(self, model_id, family):
        s = _session()
        s.model_id = model_id
        assert s.model_family() == family


class TestProjectStats:
    def test_dominant_model_majority(self):
        p = ProjectStats(project_dir="/p")
        p.sessions = [_session(), _session()]
        # both default to claude-opus → opus dominates
        assert p.dominant_model() == "opus"

    def test_dominant_model_empty_is_other(self):
        assert ProjectStats(project_dir="/p").dominant_model() == "other"

    def test_project_name_extracts_last_component(self):
        assert ProjectStats(project_dir="/a/b/c").project_name() == "c"
        assert ProjectStats(project_dir="noslash").project_name() == "noslash"

    def test_totals_and_ratio(self):
        p = ProjectStats(
            project_dir="/p",
            total_input_tokens=10,
            total_output_tokens=10,
            total_cache_creation=20,
            total_cache_read=60,
        )
        assert p.total_tokens() == 100
        assert p.cache_hit_ratio() == pytest.approx(60.0)
        assert ProjectStats(project_dir="/p").cache_hit_ratio() == 0.0


# ---------------------------------------------------------------------------
# _load_session_stats — parsing, corruption, IO failures
# ---------------------------------------------------------------------------


class TestLoadSessionStats:
    def test_happy_path_aggregates_final_entry(self, tmp_path):
        f = tmp_path / "statusline.sess1.state"
        f.write_text(
            "\n".join(
                [
                    _csv_line(ts=1000, sid="sess1", proj="/w/alpha"),
                    _csv_line(ts=2000, sid="sess1", proj="/w/alpha"),
                ]
            )
            + "\n"
        )
        stats = _load_session_stats(f)
        assert stats is not None
        assert stats.session_id == "sess1"
        assert stats.project_dir == "/w/alpha"
        assert stats.start_time == 1000
        assert stats.end_time == 2000
        assert stats.entry_count == 2
        assert stats.total_input_tokens == 1000
        assert stats.cost_usd == 0.05

    def test_malformed_rows_skipped_valid_rows_kept(self, tmp_path):
        f = tmp_path / "statusline.mixed.state"
        f.write_text(
            "garbage-without-commas\n"
            ",,,\n" + _csv_line(ts=5, sid="mixed") + "\nnot-a-number,also-bad\n"
        )
        stats = _load_session_stats(f)
        assert stats is not None
        assert stats.entry_count == 1

    def test_empty_file_returns_none(self, tmp_path):
        f = tmp_path / "statusline.empty.state"
        f.write_text("\n \n")
        assert _load_session_stats(f) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert _load_session_stats(tmp_path / "nope.state") is None

    def test_unreadable_file_returns_none(self, tmp_path):
        d = tmp_path / "statusline.isdir.state"
        d.mkdir()  # opening a directory raises IsADirectoryError (an OSError)
        assert _load_session_stats(d) is None

    def test_legacy_two_field_rows_parse_with_defaults(self, tmp_path):
        f = tmp_path / "statusline.oldfmt.state"
        f.write_text("12345,777\n")
        stats = _load_session_stats(f)
        assert stats is not None
        assert stats.session_id == "oldfmt"
        assert stats.total_input_tokens == 777
        assert stats.entry_count == 1


# ---------------------------------------------------------------------------
# grouping / filtering / discovery
# ---------------------------------------------------------------------------


class TestGroupSessionsByProject:
    def test_multi_project_grouping_aggregates(self):
        sessions = [
            _session("a", "/proj/a", cost=1.0),
            _session("b", "/proj/a", cost=2.0),
            _session("c", "/proj/b", cost=4.0),
        ]
        projects = _group_sessions_by_project(sessions)
        assert set(projects) == {"/proj/a", "/proj/b"}
        pa = projects["/proj/a"]
        assert pa.session_count == 2
        assert pa.cost_usd == pytest.approx(3.0)
        assert [s.session_id for s in pa.sessions] == ["a", "b"]

    def test_since_days_filters_old_sessions_by_start(self):
        import time

        now = int(time.time())
        recent = _session("recent", start=now - 86400, end=now)
        old = _session("old", start=now - 40 * 86400, end=now - 35 * 86400)
        projects = _group_sessions_by_project([recent, old], since_days=30)
        ids = [s.session_id for p in projects.values() for s in p.sessions]
        assert ids == ["recent"]

    def test_boundary_start_exactly_at_cutoff_is_included(self):
        import time

        now = int(time.time())
        cutoff_start = now - 30 * 86400  # condition excludes only start < cutoff
        edge = _session("edge", start=cutoff_start, end=now)
        projects = _group_sessions_by_project([edge], since_days=30)
        assert [s.session_id for p in projects.values() for s in p.sessions] == ["edge"]


class TestDiscoverAndLoadAll:
    def test_discover_empty_when_dir_missing(self, state_dirs):
        assert _discover_state_files() == []

    def test_discover_skips_directories_and_sorts(self, state_dirs):
        sd = StateFile.STATE_DIR
        sd.mkdir(parents=True)
        (sd / "statusline.b.state").write_text(_csv_line(sid="b"))
        (sd / "statusline.a.state").write_text(_csv_line(sid="a"))
        (sd / "statusline.dir.state").mkdir()
        (sd / "unrelated.state").write_text("x")
        names = [f.name for f in _discover_state_files()]
        assert names == ["statusline.a.state", "statusline.b.state"]

    def test_load_all_projects_sorted_by_total_tokens_desc(self, state_dirs):
        sd = StateFile.STATE_DIR
        sd.mkdir(parents=True)
        # small project: 1 entry
        (sd / "statusline.small.state").write_text(_csv_line(sid="small", proj="/p/small") + "\n")
        # big project: final cumulative values are what count
        big_lines = [
            _csv_line(ts=1, sid="big", proj="/p/big", total_input_tokens=5000),
            _csv_line(ts=2, sid="big", proj="/p/big", total_input_tokens=90000),
        ]
        (sd / "statusline.big.state").write_text("\n".join(big_lines) + "\n")
        # unloadable file must be skipped silently
        (sd / "statusline.junk.state").write_text("@@@\n")

        projects = load_all_projects()
        assert [p.project_dir for p in projects] == ["/p/big", "/p/small"]
        assert projects[0].total_input_tokens == 90000
        assert projects[0].sessions[0].session_id == "big"

    def test_load_all_projects_respects_since_days(self, state_dirs):
        import time

        sd = StateFile.STATE_DIR
        sd.mkdir(parents=True)
        ancient_ts = int(time.time()) - 400 * 86400
        (sd / "statusline.ancient.state").write_text(
            _csv_line(ts=ancient_ts, sid="ancient", proj="/p/old") + "\n"
        )
        assert load_all_projects(since_days=30) == []


# ---------------------------------------------------------------------------
# core/state.py IO-failure recovery branches (fault injection)
# ---------------------------------------------------------------------------


class TestStateIoFailures:
    def test_read_history_oserror_warns_and_returns_empty(self, state_dirs, capsys):
        sf = StateFile("iofail")
        sf.file_path.write_text(_csv_line(sid="iofail") + "\n")
        with patch.object(Path, "read_text", side_effect=OSError("denied")):
            entries = sf.read_history()
        assert entries == []
        assert "failed to read state history" in capsys.readouterr().err

    def test_read_tail_oserror_warns_and_returns_empty(self, state_dirs, capsys):
        sf = StateFile("iotail")
        sf.file_path.write_text(_csv_line(sid="iotail") + "\n")
        # The tail read is window-bounded (F-PERF-001): the IO failure surface
        # is the shared tail_window_text helper (plus the full-read fallback).
        with patch(
            "claude_statusline.core.state.tail_window_text", side_effect=OSError("denied")
        ):
            assert sf.read_tail(5) == []
        with patch(
            "claude_statusline.core.state.tail_window_text", side_effect=OSError("denied")
        ), patch.object(Path, "read_text", side_effect=OSError("denied")):
            # Fallback path failing too must still degrade to [].
            assert sf.read_tail(5) == []
        assert "failed to read state tail" in capsys.readouterr().err

    def test_read_last_entry_oserror_warns_and_returns_none(self, state_dirs, capsys):
        sf = StateFile("iolast")
        sf.file_path.write_text(_csv_line(sid="iolast") + "\n")
        with patch(
            "claude_statusline.core.state.tail_window_text", side_effect=OSError("denied")
        ):
            assert sf.read_last_entry() is None
        assert "failed to read last entry" in capsys.readouterr().err

    def test_append_entry_oserror_on_open_warns(self, state_dirs, capsys):
        sf = StateFile("iowrite")
        sf.file_path.parent.mkdir(parents=True, exist_ok=True)
        sf.file_path.mkdir()  # os.open on a directory fails with OSError
        sf.append_entry(StateEntry.from_csv_line(_csv_line(sid="iowrite")))
        assert "failed to write state" in capsys.readouterr().err

    def test_rotate_locked_oserror_warns(self, state_dirs, capsys):
        class ExplodingHandle:
            def fileno(self):
                raise OSError("fileno denied")

            def seek(self, *a):
                raise OSError("seek denied")

        sf = StateFile("iorot")
        sf._rotate_locked(ExplodingHandle())
        assert "failed to rotate state file" in capsys.readouterr().err

    def test_rotate_lines_rollback_removes_temp_on_replace_failure(
        self, state_dirs, monkeypatch, capsys
    ):
        sf = StateFile("rollback")
        lines = [f"l{i}\n" for i in range(20)]

        def fail_replace(src, dst):
            raise OSError("replace denied")

        monkeypatch.setattr("claude_statusline.core.state.os.replace", fail_replace)
        with pytest.raises(OSError):
            sf._rotate_lines(sf.file_path, lines)
        # temp file cleaned up, target untouched
        leftovers = list(StateFile.STATE_DIR.glob("*.tmp")) if StateFile.STATE_DIR.exists() else []
        assert leftovers == []

    def test_maybe_rotate_noop_for_missing_file(self, state_dirs):
        sf = StateFile("ghost")
        sf._maybe_rotate()  # early return, no exception

    def test_maybe_rotate_oserror_warns(self, state_dirs, capsys):
        sf = StateFile("rotdir")
        sf.file_path.parent.mkdir(parents=True, exist_ok=True)
        sf.file_path.mkdir()  # open() on a directory raises OSError
        sf._maybe_rotate()
        assert "failed to rotate state file" in capsys.readouterr().err

    def test_lock_unlock_survive_flock_errors(self, monkeypatch):
        import claude_statusline.core.state as st

        class BadFcntl:
            LOCK_EX = 2
            LOCK_UN = 8

            def flock(self, *a, **k):
                raise OSError("flock unsupported")

        monkeypatch.setattr(st, "fcntl", BadFcntl())

        class FakeHandle:
            def fileno(self):
                return 0

        st._lock_state_file(FakeHandle())  # swallowed
        st._unlock_state_file(FakeHandle())  # swallowed

    def test_list_sessions_round_trip(self, state_dirs):
        sd = StateFile.STATE_DIR
        sd.mkdir(parents=True)
        (sd / "statusline.alpha.state").write_text("")
        (sd / "statusline.beta.state").write_text("")
        (sd / "statusline..state").write_text("")  # empty id ignored
        (sd / "other.txt").write_text("")
        assert sorted(StateFile(None).list_sessions()) == ["alpha", "beta"]

    def test_from_csv_line_safe_int_float_fallbacks(self):
        row = "1710288000,abc,def,ghi,jkl,mno,pqr,vwx,stu,yz,ab,cd,ef,gh,ij\n"
        entry = StateEntry.from_csv_line(row)
        assert entry is not None
        assert entry.timestamp == 1710288000
        assert entry.total_input_tokens == 0
        assert entry.cost_usd == 0.0
