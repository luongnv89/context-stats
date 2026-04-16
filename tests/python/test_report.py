"""Tests for the report command."""

from datetime import datetime, timedelta

from claude_statusline.analytics import (
    ProjectStats,
    SessionStats,
    _group_sessions_by_project,
)
from claude_statusline.cli.report import generate_report


def _make_session(
    session_id, start_offset_days=0, end_offset_days=0, project_dir="/home/user/proj"
):
    """Return a SessionStats with start/end times relative to now."""
    now = int(datetime.now().timestamp())
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

    expected_start = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
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
