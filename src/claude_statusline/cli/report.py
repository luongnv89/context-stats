"""Report command — generates comprehensive token usage analytics.

Usage:
    context-stats report [--output FILE] [--since-days N]

Analyzes token consumption across all Claude Code projects and generates
a markdown report with executive summary, model breakdown, cost optimization,
activity heatmaps, and per-project details.

Structure (Task 5.5, F-CLEAN-002): ``generate_report`` is an orchestrator over
per-section render helpers. Aggregates are computed once into a
:class:`_ReportData` bundle; each ``_section_*`` helper returns its markdown
lines as ``list[str]`` so sections stay independently testable and small.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from claude_statusline import __version__
from claude_statusline.analytics import ProjectStats, SessionStats, load_all_projects
from claude_statusline.formatters.tokens import format_tokens

_FAKE_PREFIXES = ("test-", "abc123", "test-ses", "test-com", "test-wid")


def _parse_report_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="context-stats report",
        description="Generate comprehensive token usage analytics",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file path (default: context-stats-report-<timestamp>.md)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Only include sessions from the last N days",
    )
    return parser.parse_args(argv)


def _safe_datetime(ts: float) -> datetime | None:
    """Convert ``ts`` to a local datetime, or None when it is out of range.

    One corrupt timestamp in a state file must not crash the whole report
    (F-BUG-012): ``datetime.fromtimestamp`` raises ValueError/OSError/
    OverflowError for absurd values.
    """
    try:
        return datetime.fromtimestamp(ts)
    except (ValueError, OSError, OverflowError):
        return None


def _format_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _is_fake_session(session: SessionStats) -> bool:
    sid = session.session_id.lower()
    return any(sid.startswith(p) for p in _FAKE_PREFIXES)


def _bar(value: float, max_value: float, width: int = 20) -> str:
    if max_value <= 0:
        return "." * width
    filled = round(value / max_value * width)
    filled = max(0, min(filled, width))
    return "#" * filled + "." * (width - filled)


def _iso_week(ts: int) -> str:
    """ISO week label ``YYYY-Wnn`` for ``ts``, or "unknown" when corrupt.

    Falls back gracefully on out-of-range timestamps (F-BUG-012) instead of
    crashing the weekly-trend aggregation; callers skip "unknown" buckets.
    """
    dt = _safe_datetime(ts)
    if dt is None:
        return "unknown"
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _all_sessions(projects: list[ProjectStats]) -> list[SessionStats]:
    sessions = []
    for p in projects:
        sessions.extend(p.sessions)
    return sessions


@dataclass
class _ReportData:
    """Aggregates shared by every section renderer of the report."""

    projects_stats: list[ProjectStats]
    all_sessions: list[SessionStats]
    real_sessions: list[SessionStats]
    fake_sessions: list[SessionStats]
    total_tokens: int
    total_cost: float
    total_sessions: int
    time_scope: str
    cache_read_total: int
    avg_session_cost: float
    avg_duration: int
    most_expensive_session: SessionStats | None
    most_expensive_project: ProjectStats | None
    model_stats: dict[str, dict] = field(default_factory=dict)

    @property
    def total_projects(self) -> int:
        return len(self.projects_stats)

    def cache_hit_ratio_pct(self) -> float:
        return self.cache_read_total / self.total_tokens * 100 if self.total_tokens > 0 else 0.0

    def cost_share(self, cost: float) -> float:
        return cost / self.total_cost * 100 if self.total_cost > 0 else 0


def _collect_report_data(projects_stats: list[ProjectStats], since_days: int | None) -> _ReportData:
    """Compute every aggregate the section renderers need, exactly once."""
    all_sessions = _all_sessions(projects_stats)
    real_sessions = [s for s in all_sessions if not _is_fake_session(s)]
    fake_sessions = [s for s in all_sessions if _is_fake_session(s)]

    total_tokens = sum(s.total_tokens() for s in all_sessions)
    total_cost = sum(s.cost_usd for s in all_sessions)
    total_sessions = len(all_sessions)

    cache_read_total = sum(s.total_cache_read for s in all_sessions)
    avg_session_cost = total_cost / total_sessions if total_sessions > 0 else 0.0
    durations = [s.end_time - s.start_time for s in all_sessions if s.end_time > s.start_time]
    avg_duration = int(sum(durations) / len(durations)) if durations else 0

    most_expensive_session = max(all_sessions, key=lambda s: s.cost_usd, default=None)
    most_expensive_project = max(projects_stats, key=lambda p: p.cost_usd, default=None)

    # Compute report time scope from session data. Timestamps are converted
    # defensively so one corrupt value degrades to "unknown" instead of
    # crashing the report (F-BUG-012).
    all_end_dts = [
        dt for dt in (_safe_datetime(s.end_time) for s in all_sessions if s.end_time > 0) if dt
    ]
    if since_days is not None:
        cutoff = datetime.now() - timedelta(days=since_days)
        scope_from = cutoff.strftime("%Y-%m-%d")
    else:
        all_start_dts = [
            dt
            for dt in (_safe_datetime(s.start_time) for s in all_sessions if s.start_time > 0)
            if dt
        ]
        scope_from = min(all_start_dts).strftime("%Y-%m-%d") if all_start_dts else "unknown"
    scope_to = max(all_end_dts).strftime("%Y-%m-%d") if all_end_dts else "unknown"

    model_stats: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "tokens": 0, "cost": 0.0})
    for s in all_sessions:
        fam = s.model_family()
        model_stats[fam]["sessions"] += 1
        model_stats[fam]["tokens"] += s.total_tokens()
        model_stats[fam]["cost"] += s.cost_usd

    return _ReportData(
        projects_stats=projects_stats,
        all_sessions=all_sessions,
        real_sessions=real_sessions,
        fake_sessions=fake_sessions,
        total_tokens=total_tokens,
        total_cost=total_cost,
        total_sessions=total_sessions,
        time_scope=f"{scope_from} → {scope_to}",
        cache_read_total=cache_read_total,
        avg_session_cost=avg_session_cost,
        avg_duration=avg_duration,
        most_expensive_session=most_expensive_session,
        most_expensive_project=most_expensive_project,
        model_stats=model_stats,
    )


def _project_short_name(project_dir: str) -> str:
    return project_dir.split("/")[-1] if "/" in project_dir else project_dir


def _mermaid_xychart(title: str, labels: list[str], values: list[str], kind: str) -> list[str]:
    """Render a Mermaid xychart-beta block with quoted short labels."""
    return [
        "```mermaid",
        "xychart-beta",
        f'    title "{title}"',
        f"    x-axis [{', '.join(labels)}]",
        f"    {kind} [{', '.join(values)}]",
        "```",
        "",
    ]


def _section_header(data: _ReportData) -> list[str]:
    lines = [
        "# Token Usage Analytics Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Period: {data.time_scope}",
        f"Source: context-stats v{__version__}",
        "",
    ]
    return lines


def _section_executive_summary(data: _ReportData) -> list[str]:
    lines = [
        "## Executive Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Report Period | {data.time_scope} |",
        f"| Total Spend | ${data.total_cost:.2f} |",
        f"| Total Sessions | {data.total_sessions} |",
        f"| Projects Analyzed | {data.total_projects} |",
        f"| Cache Hit Ratio | {data.cache_hit_ratio_pct():.1f}% |",
        f"| Avg Session Cost | ${data.avg_session_cost:.2f} |",
        f"| Avg Session Duration | {_format_duration(data.avg_duration)} |",
    ]
    if data.most_expensive_session:
        pct = data.cost_share(data.most_expensive_session.cost_usd)
        lines.append(
            f"| Most Expensive Session | {data.most_expensive_session.session_id[:8]}... "
            f"(${data.most_expensive_session.cost_usd:.2f}, {pct:.1f}% of total) |"
        )
    if data.most_expensive_project:
        pct = data.cost_share(data.most_expensive_project.cost_usd)
        lines.append(
            f"| Most Expensive Project | {data.most_expensive_project.project_dir} "
            f"(${data.most_expensive_project.cost_usd:.2f}, {pct:.1f}% of total) |"
        )
    lines.append("")
    return lines


def _section_model_breakdown(data: _ReportData) -> list[str]:
    lines = [
        "## Model Usage Breakdown",
        "",
        "```mermaid",
        "pie title Model Cost Distribution",
    ]
    for fam in ("opus", "sonnet", "haiku", "other"):
        if fam not in data.model_stats:
            continue
        ms = data.model_stats[fam]
        if ms["cost"] > 0:
            lines.append(f'    "{fam.capitalize()}" : {ms["cost"]:.2f}')
    lines.extend(["```", ""])

    lines.append("| Model Family | Sessions | Total Tokens | Cost | % of Total Cost |")
    lines.append("|---|---|---|---|---|")
    for fam in ("opus", "sonnet", "haiku", "other"):
        if fam not in data.model_stats:
            continue
        ms = data.model_stats[fam]
        pct = data.cost_share(ms["cost"])
        lines.append(
            f"| {fam} | {ms['sessions']} | {format_tokens(ms['tokens'])} "
            f"| ${ms['cost']:.2f} | {pct:.1f}% |"
        )
    lines.append("")
    return lines


def _section_cost_findings(data: _ReportData) -> list[str]:
    lines = ["## Cost Optimization Analysis", "", "### Key Findings", ""]

    fake_cost = sum(s.cost_usd for s in data.fake_sessions)
    fake_pct = data.cost_share(fake_cost)
    if data.fake_sessions:
        lines.append(
            f"- **Test/Fake Sessions**: {len(data.fake_sessions)} sessions consuming "
            f"${fake_cost:.2f} ({fake_pct:.1f}% of total) "
            "— recommend removing from production analysis"
        )
        lines.append("")

    real_cost = sum(s.cost_usd for s in data.real_sessions)
    lines.append(
        f"- **Real Sessions**: {len(data.real_sessions)} sessions costing ${real_cost:.2f}"
    )

    real_cache_read = sum(s.total_cache_read for s in data.real_sessions)
    real_total_tokens = sum(s.total_tokens() for s in data.real_sessions)
    real_cache_pct = real_cache_read / real_total_tokens * 100 if real_total_tokens > 0 else 0
    lines.append(f"- **Cache Hit Ratio**: {real_cache_pct:.1f}% (room for improvement if <70%)")

    cost_per_1k = data.total_cost / (data.total_tokens / 1000) if data.total_tokens > 0 else 0
    lines.append(f"\n- **Cost per 1k tokens**: ${cost_per_1k:.3f}")
    lines.append("")
    return lines


def _section_top_cost_drivers(data: _ReportData) -> list[str]:
    lines = [
        "### Top Cost Drivers (Top 10 Sessions)",
        "| Session | Project | Cost | Cache % | Duration | Input | Output |",
        "|---------|---------|------|---------|----------|-------|--------|",
    ]
    top10 = sorted(data.all_sessions, key=lambda s: s.cost_usd, reverse=True)[:10]
    for s in top10:
        dur = _format_duration(s.end_time - s.start_time)
        cache_pct = int(s.cache_hit_ratio())
        proj_name = _project_short_name(s.project_dir)
        lines.append(
            f"| {s.session_id[:8]}... | {proj_name} | ${s.cost_usd:.2f} | {cache_pct}% "
            f"| {dur} | {format_tokens(s.total_input_tokens)} | {format_tokens(s.total_output_tokens)} |"
        )
    lines.append("")
    return lines


def _section_optimization_opportunities(data: _ReportData) -> list[str]:
    lines = ["### Optimization Opportunities", ""]

    # Low cache sessions (cache < 10%, non-fake, min cost threshold)
    low_cache = [
        s for s in data.real_sessions if s.cache_hit_ratio() < 10 and s.total_tokens() > 10000
    ]
    low_cache_sorted = sorted(low_cache, key=lambda s: s.cache_hit_ratio())[:5]
    if low_cache_sorted:
        avg_low = int(sum(s.cache_hit_ratio() for s in low_cache_sorted) / len(low_cache_sorted))
        lines.append(f"2. **Sessions with low cache efficiency** (avg {avg_low}%)")
        lines.append("   - These sessions could benefit most from optimized prompts:")
        lines.append("")
        for s in low_cache_sorted:
            proj_name = _project_short_name(s.project_dir)
            lines.append(
                f"     - {s.session_id[:8]}... ({proj_name}): {int(s.cache_hit_ratio())}% cache hit"
            )
        lines.append("")
    return lines


def _section_model_efficiency_table(data: _ReportData) -> list[str]:
    lines = [
        "3. **Model efficiency by family**",
        "   | Model | Sessions | $/1k tokens |",
        "   |-------|----------|-------------|",
    ]
    for fam in sorted(data.model_stats.keys()):
        ms = data.model_stats[fam]
        eff = ms["cost"] / (ms["tokens"] / 1000) if ms["tokens"] > 0 else 0
        lines.append(f"   | {fam} | {ms['sessions']} | ${eff:.3f} |")
    lines.append("")
    return lines


def _section_high_spend_projects(data: _ReportData) -> list[str]:
    top_projects = sorted(data.projects_stats, key=lambda p: p.cost_usd, reverse=True)[:5]
    lines = [
        "4. **High-spend projects to review**",
        "   | Project | Sessions | Cost | Cache Hit % |",
        "   |---------|----------|------|-------------|",
    ]
    for p in top_projects:
        lines.append(
            f"   | {p.project_name()} | {p.session_count} "
            f"| ${p.cost_usd:.2f} | {p.cache_hit_ratio():.0f}% |"
        )
    lines.append("")
    return lines


def _section_top_projects_chart(data: _ReportData) -> list[str]:
    top5_proj = sorted(data.projects_stats, key=lambda p: p.cost_usd, reverse=True)[:5]
    proj_labels = [f'"{p.project_name()[:8]}"' for p in top5_proj]
    proj_costs = [f"{p.cost_usd:.2f}" for p in top5_proj]
    chart = _mermaid_xychart("Top 5 Projects by Cost ($)", proj_labels, proj_costs, "bar")
    return chart


def _section_cost_efficiency(data: _ReportData) -> list[str]:
    cache_tokens_pct = data.cache_hit_ratio_pct()
    fresh_tokens_pct = 100.0 - cache_tokens_pct
    avg_tokens_per_dollar = data.total_tokens / data.total_cost if data.total_cost > 0 else 0

    lines = [
        "## Cost Efficiency",
        "",
        "```mermaid",
        "pie title Token Serving: Cache vs Fresh",
        f'    "Cache Hit" : {cache_tokens_pct:.1f}',
        f'    "Fresh (non-cached)" : {fresh_tokens_pct:.1f}',
        "```",
        "",
        f"- **Overall cache efficiency**: {cache_tokens_pct:.1f}% of tokens served from cache",
        f"- **Average tokens per dollar**: {int(avg_tokens_per_dollar)} tokens/$",
        "",
    ]

    def _efficiency_table(title: str, ordered: list[SessionStats], header: str) -> list[str]:
        rows = [title, header, "|---|---|---|---|---|"]
        for s in ordered:
            proj_name = _project_short_name(s.project_dir)
            eff = s.cost_usd / (s.total_tokens() / 1000)
            rows.append(
                f"| {s.session_id[:8]}... | {proj_name} | ${eff:.3f} | ${s.cost_usd:.2f} | {format_tokens(s.total_tokens())} |"
            )
        rows.append("")
        return rows

    sessions_with_tokens = [s for s in data.all_sessions if s.total_tokens() > 0]
    most_efficient = sorted(
        sessions_with_tokens,
        key=lambda s: s.cost_usd / (s.total_tokens() / 1000),
    )[:5]
    lines.extend(
        _efficiency_table(
            "### Top 5 Most Efficient Sessions (lowest $/1k tokens)",
            most_efficient,
            "|  Session | Project | $/1k tokens | Cost | Tokens |",
        )
    )
    least_efficient = sorted(
        sessions_with_tokens,
        key=lambda s: s.cost_usd / (s.total_tokens() / 1000),
        reverse=True,
    )[:5]
    lines.extend(
        _efficiency_table(
            "### Top 5 Least Efficient Sessions (highest $/1k tokens)",
            least_efficient,
            "| Session | Project | $/1k tokens | Cost | Tokens |",
        )
    )
    return lines


def _activity_counts(data: _ReportData) -> tuple[dict[int, int], dict[int, int]]:
    dow_counts: dict[int, int] = defaultdict(int)
    hour_counts: dict[int, int] = defaultdict(int)
    for s in data.all_sessions:
        if s.start_time:
            dt = _safe_datetime(s.start_time)
            if dt is None:
                continue  # corrupt timestamp: skip rather than crash (F-BUG-012)
            dow_counts[dt.weekday()] += 1
            hour_counts[dt.hour] += 1
    return dow_counts, hour_counts


def _section_daily_heatmap(data: _ReportData) -> list[str]:
    dow_counts, hour_counts = _activity_counts(data)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    lines = ["## Daily Activity Heatmap", ""]
    dow_labels = [f'"{d}"' for d in day_names]
    dow_values = [str(dow_counts.get(i, 0)) for i in range(7)]
    lines.extend(_mermaid_xychart("Sessions by Day of Week", dow_labels, dow_values, "bar"))

    max_dow = max(dow_counts.values(), default=1)
    lines.extend(
        ["### Sessions by Day of Week", "| Day | Count | Activity |", "|-----|-------|----------|"]
    )
    for i, name in enumerate(day_names):
        cnt = dow_counts.get(i, 0)
        lines.append(f"| {name} | {cnt} | {_bar(cnt, max_dow)} |")
    lines.append("")

    hour_labels = [f'"{h:02d}h"' for h in range(24)]
    hour_values = [str(hour_counts.get(h, 0)) for h in range(24)]
    lines.extend(_mermaid_xychart("Sessions by Hour of Day", hour_labels, hour_values, "bar"))

    max_hour = max(hour_counts.values(), default=1)
    lines.extend(
        [
            "### Sessions by Hour of Day",
            "| Hour | Count | Activity |",
            "|------|-------|----------|",
        ]
    )
    for h in range(24):
        cnt = hour_counts.get(h, 0)
        lines.append(f"| {h:02d} | {cnt} | {_bar(cnt, max_hour)} |")
    lines.append("")
    return lines


def _weekly_buckets(data: _ReportData) -> dict[str, dict]:
    week_data: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "cost": 0.0, "tokens": 0})
    for s in data.all_sessions:
        if s.start_time:
            week = _iso_week(s.start_time)
            if week == "unknown":
                continue  # corrupt timestamp: excluded from the weekly trend
            week_data[week]["sessions"] += 1
            week_data[week]["cost"] += s.cost_usd
            week_data[week]["tokens"] += s.total_tokens()
    return week_data


def _section_weekly_trend(data: _ReportData) -> list[str]:
    week_data = _weekly_buckets(data)
    sorted_weeks = sorted(week_data.keys())

    # Short labels: strip year prefix, keep only "Wnn" to avoid overlap
    short_week_labels = [f'"{w.split("-")[1]}"' for w in sorted_weeks]
    week_costs = [f"{week_data[w]['cost']:.2f}" for w in sorted_weeks]
    week_session_counts = [str(week_data[w]["sessions"]) for w in sorted_weeks]

    lines = ["## Weekly Activity Trend", ""]
    lines.extend(_mermaid_xychart("Weekly Spend ($)", short_week_labels, week_costs, "line"))
    lines.extend(
        _mermaid_xychart("Weekly Sessions Count", short_week_labels, week_session_counts, "bar")
    )

    max_week_cost = max((v["cost"] for v in week_data.values()), default=1)
    lines.extend(
        [
            "| Week | Sessions | Cost | Tokens | Spend Bar |",
            "|------|----------|------|--------|-----------|",
        ]
    )
    for week in sorted_weeks:
        wd = week_data[week]
        lines.append(
            f"| {week} | {wd['sessions']} | ${wd['cost']:.2f} "
            f"| {format_tokens(wd['tokens'])} | {_bar(wd['cost'], max_week_cost)} |"
        )
    lines.append("")
    return lines


def _git_sessions(data: _ReportData) -> list[SessionStats]:
    return [s for s in data.all_sessions if s.lines_added > 0 or s.lines_removed > 0]


def _section_code_productivity(data: _ReportData) -> list[str]:
    """Code Productivity section — omitted entirely without git activity data."""
    sessions_with_git = _git_sessions(data)
    if not sessions_with_git:
        return []

    total_added = sum(s.lines_added for s in sessions_with_git)
    total_removed = sum(s.lines_removed for s in sessions_with_git)
    total_lines = total_added + total_removed
    git_cost = sum(s.cost_usd for s in sessions_with_git)
    lines_per_dollar = total_lines / git_cost if git_cost > 0 else 0
    git_tokens = sum(s.total_tokens() for s in sessions_with_git)
    lines_per_1k = total_lines / (git_tokens / 1000) if git_tokens > 0 else 0

    lines = [
        "## Code Productivity",
        "",
        f"> Based on {len(sessions_with_git)} sessions with git activity data.",
        "",
        f"- **Total lines changed**: {total_lines:,} (+{total_added:,} / -{total_removed:,})",
        f"- **Lines per dollar**: {int(lines_per_dollar)} lines/$",
        f"- **Lines per 1k tokens**: {lines_per_1k:.1f} lines/1k tokens",
        "",
    ]

    proj_git: dict[str, dict] = defaultdict(lambda: {"lines": 0, "cost": 0.0})
    for s in sessions_with_git:
        proj_git[s.project_dir]["lines"] += s.lines_added + s.lines_removed
        proj_git[s.project_dir]["cost"] += s.cost_usd
    top_efficient_proj = sorted(
        proj_git.items(),
        key=lambda kv: kv[1]["lines"] / kv[1]["cost"] if kv[1]["cost"] > 0 else 0,
        reverse=True,
    )[:5]
    lines.extend(
        [
            "### Top 5 Projects by Lines/$ Efficiency",
            "| Project | Lines Changed | Cost | Lines/$ |",
            "|---------|--------------|------|---------|",
        ]
    )
    for proj_dir, pd in top_efficient_proj:
        proj_name = _project_short_name(proj_dir)
        eff = int(pd["lines"] / pd["cost"]) if pd["cost"] > 0 else 0
        lines.append(f"| {proj_name} | {pd['lines']:,} | ${pd['cost']:.2f} | {eff} |")
    lines.append("")
    return lines


def _section_projects_table(data: _ReportData) -> list[str]:
    lines = [
        "## Projects",
        "",
        "| # | Project | Sessions | Cost | % Total | Tokens | Cache Hit % | Avg Cost | Dominant Model |",
        "|---|---------|----------|------|---------|--------|-------------|----------|----------------|",
    ]
    for idx, p in enumerate(data.projects_stats, 1):
        pct = data.cost_share(p.cost_usd)
        avg_cost = p.cost_usd / p.session_count if p.session_count > 0 else 0
        lines.append(
            f"| {idx} | {p.project_name()} | {p.session_count} | ${p.cost_usd:.2f} "
            f"| {pct:.1f}% | {format_tokens(p.total_tokens())} "
            f"| {p.cache_hit_ratio():.1f}% | ${avg_cost:.2f} | {p.dominant_model()} |"
        )
    lines.extend(["", "---", "*Report generated by context-stats*"])
    return lines


# Section order preserved exactly as the pre-refactor monolith emitted it;
# the golden snapshots (tests/python/test_golden_snapshots.py) pin this.
_REPORT_SECTIONS = (
    _section_header,
    _section_executive_summary,
    _section_model_breakdown,
    _section_cost_findings,
    _section_top_cost_drivers,
    _section_optimization_opportunities,
    _section_model_efficiency_table,
    _section_high_spend_projects,
    _section_top_projects_chart,
    _section_cost_efficiency,
    _section_daily_heatmap,
    _section_weekly_trend,
    _section_code_productivity,
    _section_projects_table,
)


def generate_report(projects_stats: list[ProjectStats], since_days: int | None = None) -> str:
    """Generate the full markdown report for the given projects.

    Orchestrator only (F-CLEAN-002): aggregates are collected once into a
    :class:`_ReportData`, then each registered section renderer contributes
    its lines.
    """
    data = _collect_report_data(projects_stats, since_days)
    lines: list[str] = []
    for section in _REPORT_SECTIONS:
        lines.extend(section(data))
    return "\n".join(lines)


def run_report(argv: list[str]) -> None:
    """Execute report command."""
    args = _parse_report_args(argv)

    projects_stats = load_all_projects(since_days=args.since_days)

    if not projects_stats:
        print("No project data found in ~/.claude/statusline/", file=sys.stderr)
        sys.exit(1)

    report = generate_report(projects_stats, since_days=args.since_days)

    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = Path.cwd() / f"context-stats-report-{timestamp}.md"

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"✓ Report generated: {output_path}")
    except OSError as e:
        print(f"✗ Failed to write report: {e}", file=sys.stderr)
        sys.exit(1)
