"""Tests for the report command."""

from datetime import datetime, timedelta

import pytest

import claude_statusline.analytics as analytics_mod
import claude_statusline.cli.report as report_mod
from claude_statusline.analytics import (
    ProjectStats,
    SessionStats,
    _group_sessions_by_project,
)
from claude_statusline.cli.report import generate_report

# Frozen clock shared by every datetime.now() read in this module (F-TEST-008).
# The fixture below swaps it into both modules that read the wall clock, so a
# midnight straddle during a CI run can no longer split two reads across days.
_FROZEN_NOW = datetime(2026, 6, 15, 12, 0, 0)


class _FrozenDatetime(datetime):
    """datetime stand-in whose now() always returns _FROZEN_NOW.

    Everything else (fromtimestamp, strftime via instances) delegates to the
    real implementation because it subclasses datetime.
    """

    @classmethod
    def now(cls, tz=None):  # noqa: N802 - mirrors datetime API
        if tz is not None:
            return _FROZEN_NOW.replace(tzinfo=tz)
        return _FROZEN_NOW


@pytest.fixture(autouse=True)
def frozen_report_clock(monkeypatch):
    """Pin datetime.now() in report and analytics to _FROZEN_NOW."""
    monkeypatch.setattr(report_mod, "datetime", _FrozenDatetime)
    monkeypatch.setattr(analytics_mod, "datetime", _FrozenDatetime)


def _make_session(
    session_id, start_offset_days=0, end_offset_days=0, project_dir="/home/user/proj"
):
    """Return a SessionStats with start/end times relative to the frozen clock."""
    now = int(_FROZEN_NOW.timestamp())
    start = now - int(start_offset_days * 86400)
    end = now - int(end_offset_days * 86400)
    return SessionStats(
        session_id=session_id,
        project_dir=project_dir,
        model_id="claude-opus",
        total_input_tokens=1000,
        total_output_tokens=200,
        total_cache_creation=100,
        total_cache_read=50,
        cost_usd=0.05,
        start_time=start,
        end_time=end,
        entry_count=2,
    )


def test_generate_report_with_projects():
    """Test report generation with sample project data."""
    # Create sample data
    session1 = SessionStats(
        session_id="abc123",
        project_dir="/home/user/project1",
        model_id="claude-opus",
        total_input_tokens=10000,
        total_output_tokens=2000,
        total_cache_creation=1000,
        total_cache_read=500,
        cost_usd=0.15,
        start_time=1000000,
        end_time=1000300,
        entry_count=10,
    )

    session2 = SessionStats(
        session_id="def456",
        project_dir="/home/user/project1",
        model_id="claude-sonnet",
        total_input_tokens=5000,
        total_output_tokens=1000,
        total_cache_creation=500,
        total_cache_read=200,
        cost_usd=0.08,
        start_time=1001000,
        end_time=1001200,
        entry_count=5,
    )

    project1 = ProjectStats(
        project_dir="/home/user/project1",
        total_input_tokens=15000,
        total_output_tokens=3000,
        total_cache_creation=1500,
        total_cache_read=700,
        cost_usd=0.23,
        session_count=2,
        sessions=[session1, session2],
    )

    report = generate_report([project1])

    # Verify report contains expected elements
    assert "Token Usage Analytics Report" in report
    assert "Executive Summary" in report
    assert "Model Usage Breakdown" in report
    assert "Cost Optimization Analysis" in report
    assert "Daily Activity Heatmap" in report
    assert "Weekly Activity Trend" in report
    assert "Projects" in report
    assert "/home/user/project1" in report
    assert "abc123" in report
    assert "def456" in report
    assert "Sessions" in report


def test_generate_report_empty():
    """Test report generation with no data."""
    report = generate_report([])

    # Verify report still has structure even with no projects
    assert "Token Usage Analytics Report" in report
    assert "Executive Summary" in report
    assert "0" in report  # Should show 0 sessions


def test_report_period_without_since_days():
    """Period should reflect the actual earliest start and latest end from session data."""
    session = SessionStats(
        session_id="abc",
        project_dir="/proj",
        model_id="claude-opus",
        total_input_tokens=100,
        total_output_tokens=10,
        total_cache_creation=0,
        total_cache_read=0,
        cost_usd=0.01,
        start_time=1700000000,  # 2023-11-14
        end_time=1700100000,  # ~1 day later
        entry_count=1,
    )
    project = ProjectStats(
        project_dir="/proj",
        total_input_tokens=100,
        total_output_tokens=10,
        cost_usd=0.01,
        session_count=1,
        sessions=[session],
    )
    report = generate_report([project])
    assert "2023-11-14" in report
    assert "Period:" in report


def test_report_period_with_since_days():
    """When since_days is given, the period start must match the cutoff date, not session data."""
    session = SessionStats(
        session_id="abc",
        project_dir="/proj",
        model_id="claude-opus",
        total_input_tokens=100,
        total_output_tokens=10,
        total_cache_creation=0,
        total_cache_read=0,
        cost_usd=0.01,
        start_time=1700000000,  # far in the past
        end_time=1700100000,
        entry_count=1,
    )
    project = ProjectStats(
        project_dir="/proj",
        total_input_tokens=100,
        total_output_tokens=10,
        cost_usd=0.01,
        session_count=1,
        sessions=[session],
    )
    since_days = 7
    report = generate_report([project], since_days=since_days)

    # Same frozen clock the report reads — no independent live read (F-TEST-008).
    expected_start = (_FROZEN_NOW - timedelta(days=since_days)).strftime("%Y-%m-%d")
    assert expected_start in report
    # The old session start date (2023) must NOT appear as the period start
    assert "2023-11-14" not in report.split("Period:")[1].split("\n")[0]


def test_since_days_filters_by_start_time():
    """Sessions whose start_time predates the cutoff must be excluded."""
    old_session = _make_session("old-session", start_offset_days=40, end_offset_days=35)
    recent_session = _make_session("recent-session", start_offset_days=3, end_offset_days=1)

    all_sessions = [old_session, recent_session]
    projects = _group_sessions_by_project(all_sessions, since_days=30)

    session_ids = [s.session_id for p in projects.values() for s in p.sessions]
    assert "recent-session" in session_ids
    assert "old-session" not in session_ids


def test_since_days_does_not_filter_by_end_time():
    """A session that started within the window must be included even if it ended earlier (edge case)."""
    # Session started 5 days ago (within 30-day window) — should be included
    included = _make_session("included", start_offset_days=5, end_offset_days=3)
    # Session started 40 days ago (outside 30-day window) — should be excluded
    excluded = _make_session("excluded", start_offset_days=40, end_offset_days=2)

    projects = _group_sessions_by_project([included, excluded], since_days=30)
    session_ids = [s.session_id for p in projects.values() for s in p.sessions]

    assert "included" in session_ids
    assert "excluded" not in session_ids


# ---------------------------------------------------------------------------
# Issue #130 / F-BUG-012 — corrupt timestamps must not crash the report
# ---------------------------------------------------------------------------

# Values that make datetime.fromtimestamp raise (OverflowError/ValueError/
# OSError depending on platform).
CORRUPT_TIMESTAMPS = [10**20, -(10**12)]


def _project_with(session):
    return ProjectStats(
        project_dir=session.project_dir,
        total_input_tokens=session.total_input_tokens,
        total_output_tokens=session.total_output_tokens,
        cost_usd=session.cost_usd,
        session_count=1,
        sessions=[session],
    )


def test_iso_week_valid_timestamp():
    from claude_statusline.cli.report import _iso_week

    dt = datetime(2026, 1, 15)  # a Thursday
    label = _iso_week(int(dt.timestamp()))
    assert label.startswith("2026-W")
    assert len(label) == 8


@pytest.mark.parametrize("bad_ts", CORRUPT_TIMESTAMPS)
def test_iso_week_corrupt_timestamp_falls_back(bad_ts):
    """_iso_week returns 'unknown' instead of raising on absurd values."""
    from claude_statusline.cli.report import _iso_week

    assert _iso_week(bad_ts) == "unknown"


@pytest.mark.parametrize("bad_ts", CORRUPT_TIMESTAMPS)
def test_report_survives_corrupt_start_time(bad_ts):
    """One corrupt timestamp must not crash report generation (F-BUG-012)."""
    good = _make_session("good-session", start_offset_days=2, end_offset_days=1)
    corrupt = SessionStats(
        session_id="corrupt-session",
        project_dir="/proj",
        model_id="claude-opus",
        total_input_tokens=100,
        start_time=bad_ts,
        end_time=0,
        cost_usd=0.01,
        entry_count=1,
    )
    project = ProjectStats(
        project_dir="/proj",
        sessions=[good, corrupt],
        session_count=2,
    )
    report = generate_report([project])
    assert "Token Usage Analytics Report" in report
    # The weekly trend excludes the unknown bucket rather than crashing.
    assert "unknown" not in report.split("## Weekly Activity Trend")[1].split("```mermaid")[1]
