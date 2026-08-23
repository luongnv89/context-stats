"""Byte-exact golden snapshots for the report and export markdown renderers.

Captured from the pre-refactor implementation (issues #146, F-CLEAN-002/005):
every fixture file in ``fixtures/`` must keep rendering byte-identically while
``generate_report`` is split into per-section helpers and
``_generate_exec_snapshot`` is converted to a ``SessionSnapshot`` dataclass.

Both renderers read the wall clock for their "Generated" stamp, so the freeze
strategy of ``test_report.py`` (F-TEST-008) is reused here.
"""

from datetime import datetime
from pathlib import Path

import pytest

import claude_statusline.analytics as analytics_mod
import claude_statusline.cli.export as export_mod
import claude_statusline.cli.report as report_mod
from claude_statusline.analytics import ProjectStats, SessionStats
from claude_statusline.cli.export import _generate_markdown
from claude_statusline.cli.report import generate_report
from claude_statusline.core.config import Config
from claude_statusline.core.state import StateEntry

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPORT_GOLDEN = FIXTURES_DIR / "report_golden.md"
EXPORT_GOLDEN = FIXTURES_DIR / "export_golden.md"

_FROZEN_NOW = datetime(2026, 6, 15, 12, 0, 0)
_BASE = 1749945600


class _FrozenDatetime(datetime):
    """datetime stand-in whose now() always returns _FROZEN_NOW."""

    @classmethod
    def now(cls, tz=None):  # noqa: N802 - mirrors datetime API
        if tz is not None:
            return _FROZEN_NOW.replace(tzinfo=tz)
        return _FROZEN_NOW


@pytest.fixture
def frozen_render_clock(monkeypatch):
    """Pin every wall-clock read behind the golden fixtures."""
    monkeypatch.setattr(report_mod, "datetime", _FrozenDatetime)
    monkeypatch.setattr(analytics_mod, "datetime", _FrozenDatetime)
    monkeypatch.setattr(export_mod, "datetime", _FrozenDatetime)


def _sess(sid, project, model, inp, out, cc, cr, cost, start, end, added=0, removed=0):
    return SessionStats(
        session_id=sid,
        project_dir=project,
        model_id=model,
        total_input_tokens=inp,
        total_output_tokens=out,
        total_cache_creation=cc,
        total_cache_read=cr,
        cost_usd=cost,
        start_time=start,
        end_time=end,
        entry_count=3,
        lines_added=added,
        lines_removed=removed,
    )


def _golden_projects() -> list[ProjectStats]:
    """Two projects / four real sessions + one fake, covering the report's branches:
    multiple model families, a fake session (Key Findings), a low-cache heavy
    session (Optimization Opportunities), and git activity (Code Productivity)."""
    s1 = _sess("a1b2c3d4e5f6", "/home/user/alpha", "claude-opus", 40_000, 8_000,
               4_000, 60_000, 1.20, _BASE - 3 * 86400, _BASE - 3 * 86400 + 3600,
               added=120, removed=30)
    s2 = _sess("b2c3d4e5f6a1", "/home/user/alpha", "claude-sonnet", 25_000, 5_000,
               2_000, 18_000, 0.45, _BASE - 2 * 86400, _BASE - 2 * 86400 + 1800)
    s3 = _sess("c3d4e5f6a1b2", "/home/user/beta", "claude-haiku", 90_000, 900,
               100, 200, 0.03, _BASE - 86400, _BASE - 86400 + 600)
    s4 = _sess("d4e5f6a1b2c3", "/home/user/beta", "claude-3-unknown", 12_000, 2_500,
               500, 1_000, 0.10, _BASE - 3600, _BASE, added=45, removed=7)
    fake = _sess("test-fake-0001", "/home/user/alpha", "claude-opus", 1_000, 100,
                 10, 20, 0.02, _BASE - 7200, _BASE - 7000)

    alpha = ProjectStats(
        project_dir="/home/user/alpha",
        total_input_tokens=66_000,
        total_output_tokens=13_100,
        total_cache_creation=6_010,
        total_cache_read=78_020,
        cost_usd=1.67,
        session_count=3,
        sessions=[s1, s2, fake],
    )
    beta = ProjectStats(
        project_dir="/home/user/beta",
        total_input_tokens=102_000,
        total_output_tokens=3_400,
        total_cache_creation=600,
        total_cache_read=1_200,
        cost_usd=0.13,
        session_count=2,
        sessions=[s3, s4],
    )
    return [alpha, beta]


def _golden_entry(ts, cur_in, cur_out, cc, cr, cost=0.5, added=0, removed=0):
    return StateEntry(
        timestamp=ts,
        total_input_tokens=cur_in * 2,
        total_output_tokens=cur_out * 2,
        current_input_tokens=cur_in,
        current_output_tokens=cur_out,
        cache_creation=cc,
        cache_read=cr,
        cost_usd=cost,
        lines_added=added,
        lines_removed=removed,
        session_id="golden-export-session",
        model_id="claude-opus",
        workspace_project_dir="/home/user/alpha",
        context_window_size=200_000,
        api_duration_ms=12_000,
    )


def test_report_golden_bytes(frozen_render_clock):
    """generate_report output stays byte-identical across the section split."""
    expected = REPORT_GOLDEN.read_text(encoding="utf-8")
    assert generate_report(_golden_projects()) == expected


def test_export_golden_bytes(frozen_render_clock):
    """_generate_markdown output stays byte-identical through the snapshot dataclass."""
    entries = [
        _golden_entry(_BASE, 5_000, 300, 100, 400),
        _golden_entry(_BASE + 120, 25_000, 800, 1_500, 9_000, cost=0.9),
        _golden_entry(_BASE + 240, 95_000, 1_200, 2_000, 80_000, cost=1.7),
        _golden_entry(_BASE + 360, 140_000, 900, 500, 30_000, cost=2.1,
                      added=210, removed=55),
        _golden_entry(_BASE + 480, 150_000, 700, 300, 12_000, cost=2.4),
    ]
    expected = EXPORT_GOLDEN.read_text(encoding="utf-8")
    assert _generate_markdown(entries, "golden-export-session", Config()) == expected
