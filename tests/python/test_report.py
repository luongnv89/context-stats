"""Tests for the report command."""

from claude_statusline.analytics import ProjectStats, SessionStats
from claude_statusline.cli.report import generate_report


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
