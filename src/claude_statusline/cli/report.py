"""Report command — generates comprehensive token usage analytics.

Usage:
    context-stats report [--output FILE] [--since-days N]

Analyzes token consumption across all Claude Code projects and generates
a markdown report with executive summary, model breakdown, cost optimization,
activity heatmaps, and per-project details.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
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


def _format_timestamp(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return str(ts)


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
    dt = datetime.fromtimestamp(ts)
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _all_sessions(projects: list[ProjectStats]) -> list[SessionStats]:
    sessions = []
    for p in projects:
        sessions.extend(p.sessions)
    return sessions


def generate_report(projects_stats: list[ProjectStats]) -> str:
    lines: list[str] = []

    all_sessions = _all_sessions(projects_stats)
    real_sessions = [s for s in all_sessions if not _is_fake_session(s)]
    fake_sessions = [s for s in all_sessions if _is_fake_session(s)]

    total_tokens = sum(s.total_tokens() for s in all_sessions)
    total_cost = sum(s.cost_usd for s in all_sessions)
    total_sessions = len(all_sessions)
    total_projects = len(projects_stats)

    cache_read_total = sum(s.total_cache_read for s in all_sessions)
    cache_hit_ratio = cache_read_total / total_tokens * 100 if total_tokens > 0 else 0.0

    avg_session_cost = total_cost / total_sessions if total_sessions > 0 else 0.0
    durations = [s.end_time - s.start_time for s in all_sessions if s.end_time > s.start_time]
    avg_duration = int(sum(durations) / len(durations)) if durations else 0

    most_expensive_session = max(all_sessions, key=lambda s: s.cost_usd, default=None)
    most_expensive_project = max(projects_stats, key=lambda p: p.cost_usd, default=None)

    # Header
    lines.append("# Token Usage Analytics Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Source: cc-context-stats v{__version__}")
    lines.append("")

    # Executive Summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Spend | ${total_cost:.2f} |")
    lines.append(f"| Total Sessions | {total_sessions} |")
    lines.append(f"| Projects Analyzed | {total_projects} |")
    lines.append(f"| Cache Hit Ratio | {cache_hit_ratio:.1f}% |")
    lines.append(f"| Avg Session Cost | ${avg_session_cost:.2f} |")
    lines.append(f"| Avg Session Duration | {_format_duration(avg_duration)} |")
    if most_expensive_session:
        pct = most_expensive_session.cost_usd / total_cost * 100 if total_cost > 0 else 0
        lines.append(
            f"| Most Expensive Session | {most_expensive_session.session_id[:8]}... "
            f"(${most_expensive_session.cost_usd:.2f}, {pct:.1f}% of total) |"
        )
    if most_expensive_project:
        pct = most_expensive_project.cost_usd / total_cost * 100 if total_cost > 0 else 0
        lines.append(
            f"| Most Expensive Project | {most_expensive_project.project_dir} "
            f"(${most_expensive_project.cost_usd:.2f}, {pct:.1f}% of total) |"
        )
    lines.append("")

    # Model Usage Breakdown
    lines.append("## Model Usage Breakdown")
    lines.append("")
    model_stats: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "tokens": 0, "cost": 0.0})
    for s in all_sessions:
        fam = s.model_family()
        model_stats[fam]["sessions"] += 1
        model_stats[fam]["tokens"] += s.total_tokens()
        model_stats[fam]["cost"] += s.cost_usd

    # Mermaid pie chart: model cost distribution
    lines.append("```mermaid")
    lines.append('pie title Model Cost Distribution')
    for fam in ("opus", "sonnet", "haiku", "other"):
        if fam not in model_stats:
            continue
        ms = model_stats[fam]
        if ms["cost"] > 0:
            lines.append(f'    "{fam.capitalize()}" : {ms["cost"]:.2f}')
    lines.append("```")
    lines.append("")

    lines.append("| Model Family | Sessions | Total Tokens | Cost | % of Total Cost |")
    lines.append("|---|---|---|---|---|")
    for fam in ("opus", "sonnet", "haiku", "other"):
        if fam not in model_stats:
            continue
        ms = model_stats[fam]
        pct = ms["cost"] / total_cost * 100 if total_cost > 0 else 0
        lines.append(
            f"| {fam} | {ms['sessions']} | {format_tokens(ms['tokens'])} "
            f"| ${ms['cost']:.2f} | {pct:.1f}% |"
        )
    lines.append("")

    # Cost Optimization Analysis
    lines.append("## Cost Optimization Analysis")
    lines.append("")
    lines.append("### Key Findings")
    lines.append("")

    fake_cost = sum(s.cost_usd for s in fake_sessions)
    fake_pct = fake_cost / total_cost * 100 if total_cost > 0 else 0
    if fake_sessions:
        lines.append(
            f"- **Test/Fake Sessions**: {len(fake_sessions)} sessions consuming "
            f"${fake_cost:.2f} ({fake_pct:.1f}% of total) "
            "— recommend removing from production analysis"
        )
        lines.append("")

    real_cost = sum(s.cost_usd for s in real_sessions)
    lines.append(f"- **Real Sessions**: {len(real_sessions)} sessions costing ${real_cost:.2f}")

    real_cache_read = sum(s.total_cache_read for s in real_sessions)
    real_total_tokens = sum(s.total_tokens() for s in real_sessions)
    real_cache_pct = real_cache_read / real_total_tokens * 100 if real_total_tokens > 0 else 0
    lines.append(
        f"- **Cache Hit Ratio**: {real_cache_pct:.1f}% "
        f"(room for improvement if <70%)"
    )

    cost_per_1k = total_cost / (total_tokens / 1000) if total_tokens > 0 else 0
    lines.append(f"\n- **Cost per 1k tokens**: ${cost_per_1k:.3f}")
    lines.append("")

    # Top 10 sessions
    lines.append("### Top Cost Drivers (Top 10 Sessions)")
    lines.append("| Session | Project | Cost | Cache % | Duration | Input | Output |")
    lines.append("|---------|---------|------|---------|----------|-------|--------|")
    top10 = sorted(all_sessions, key=lambda s: s.cost_usd, reverse=True)[:10]
    for s in top10:
        dur = _format_duration(s.end_time - s.start_time)
        cache_pct = int(s.cache_hit_ratio())
        proj_name = s.project_dir.split("/")[-1] if "/" in s.project_dir else s.project_dir
        lines.append(
            f"| {s.session_id[:8]}... | {proj_name} | ${s.cost_usd:.2f} | {cache_pct}% "
            f"| {dur} | {format_tokens(s.total_input_tokens)} | {format_tokens(s.total_output_tokens)} |"
        )
    lines.append("")

    # Optimization opportunities
    lines.append("### Optimization Opportunities")
    lines.append("")

    # Low cache sessions (cache < 10%, non-fake, min cost threshold)
    low_cache = [
        s for s in real_sessions
        if s.cache_hit_ratio() < 10 and s.total_tokens() > 10000
    ]
    low_cache_sorted = sorted(low_cache, key=lambda s: s.cache_hit_ratio())[:5]
    if low_cache_sorted:
        lines.append(
            f"2. **Sessions with low cache efficiency** (avg {int(sum(s.cache_hit_ratio() for s in low_cache_sorted) / len(low_cache_sorted))}%)"
        )
        lines.append("   - These sessions could benefit most from optimized prompts:")
        lines.append("")
        for s in low_cache_sorted:
            proj_name = s.project_dir.split("/")[-1] if "/" in s.project_dir else s.project_dir
            lines.append(f"     - {s.session_id[:8]}... ({proj_name}): {int(s.cache_hit_ratio())}% cache hit")
        lines.append("")

    # Model efficiency
    lines.append("3. **Model efficiency by family**")
    lines.append("   | Model | Sessions | $/1k tokens |")
    lines.append("   |-------|----------|-------------|")
    for fam in sorted(model_stats.keys()):
        ms = model_stats[fam]
        eff = ms["cost"] / (ms["tokens"] / 1000) if ms["tokens"] > 0 else 0
        lines.append(f"   | {fam} | {ms['sessions']} | ${eff:.3f} |")
    lines.append("")

    # High-spend projects
    top_projects = sorted(projects_stats, key=lambda p: p.cost_usd, reverse=True)[:5]
    lines.append("4. **High-spend projects to review**")
    lines.append("   | Project | Sessions | Cost | Cache Hit % |")
    lines.append("   |---------|----------|------|-------------|")
    for p in top_projects:
        lines.append(
            f"   | {p.project_name()} | {p.session_count} "
            f"| ${p.cost_usd:.2f} | {p.cache_hit_ratio():.0f}% |"
        )
    lines.append("")

    # Mermaid bar chart: top 5 projects by cost (short labels to avoid overlap)
    lines.append("```mermaid")
    lines.append("xychart-beta")
    lines.append('    title "Top 5 Projects by Cost ($)"')
    top5_proj = sorted(projects_stats, key=lambda p: p.cost_usd, reverse=True)[:5]
    proj_labels = [f'"{p.project_name()[:8]}"' for p in top5_proj]
    proj_costs = [f"{p.cost_usd:.2f}" for p in top5_proj]
    lines.append(f'    x-axis [{", ".join(proj_labels)}]')
    lines.append(f'    bar [{", ".join(proj_costs)}]')
    lines.append("```")
    lines.append("")

    # Cost Efficiency
    lines.append("## Cost Efficiency")
    lines.append("")
    cache_tokens = sum(s.total_cache_read for s in all_sessions)
    cache_tokens_pct = (cache_tokens / total_tokens * 100) if total_tokens > 0 else 0
    fresh_tokens_pct = 100.0 - cache_tokens_pct
    avg_tokens_per_dollar = total_tokens / total_cost if total_cost > 0 else 0

    # Mermaid pie chart: cache vs fresh tokens
    lines.append("```mermaid")
    lines.append('pie title Token Serving: Cache vs Fresh')
    lines.append(f'    "Cache Hit" : {cache_tokens_pct:.1f}')
    lines.append(f'    "Fresh (non-cached)" : {fresh_tokens_pct:.1f}')
    lines.append("```")
    lines.append("")

    lines.append(f"- **Overall cache efficiency**: {cache_tokens_pct:.1f}% of tokens served from cache")
    lines.append(f"- **Average tokens per dollar**: {int(avg_tokens_per_dollar)} tokens/$")
    lines.append("")

    # Most efficient (lowest $/1k)
    sessions_with_tokens = [s for s in all_sessions if s.total_tokens() > 0]
    most_efficient = sorted(
        sessions_with_tokens,
        key=lambda s: s.cost_usd / (s.total_tokens() / 1000),
    )[:5]
    lines.append("### Top 5 Most Efficient Sessions (lowest $/1k tokens)")
    lines.append("|  Session | Project | $/1k tokens | Cost | Tokens |")
    lines.append("|---|---|---|---|---|")
    for s in most_efficient:
        proj_name = s.project_dir.split("/")[-1] if "/" in s.project_dir else s.project_dir
        eff = s.cost_usd / (s.total_tokens() / 1000)
        lines.append(
            f"| {s.session_id[:8]}... | {proj_name} | ${eff:.3f} | ${s.cost_usd:.2f} | {format_tokens(s.total_tokens())} |"
        )
    lines.append("")

    # Least efficient (highest $/1k)
    least_efficient = sorted(
        sessions_with_tokens,
        key=lambda s: s.cost_usd / (s.total_tokens() / 1000),
        reverse=True,
    )[:5]
    lines.append("### Top 5 Least Efficient Sessions (highest $/1k tokens)")
    lines.append("| Session | Project | $/1k tokens | Cost | Tokens |")
    lines.append("|---|---|---|---|---|")
    for s in least_efficient:
        proj_name = s.project_dir.split("/")[-1] if "/" in s.project_dir else s.project_dir
        eff = s.cost_usd / (s.total_tokens() / 1000)
        lines.append(
            f"| {s.session_id[:8]}... | {proj_name} | ${eff:.3f} | ${s.cost_usd:.2f} | {format_tokens(s.total_tokens())} |"
        )
    lines.append("")

    # Daily Activity Heatmap
    lines.append("## Daily Activity Heatmap")
    lines.append("")

    dow_counts: dict[int, int] = defaultdict(int)
    hour_counts: dict[int, int] = defaultdict(int)
    for s in all_sessions:
        if s.start_time:
            dt = datetime.fromtimestamp(s.start_time)
            dow_counts[dt.weekday()] += 1
            hour_counts[dt.hour] += 1

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    # Mermaid bar chart: sessions by day of week
    lines.append("```mermaid")
    lines.append("xychart-beta")
    lines.append('    title "Sessions by Day of Week"')
    dow_labels = [f'"{d}"' for d in day_names]
    dow_values = [str(dow_counts.get(i, 0)) for i in range(7)]
    lines.append(f'    x-axis [{", ".join(dow_labels)}]')
    lines.append(f'    bar [{", ".join(dow_values)}]')
    lines.append("```")
    lines.append("")

    max_dow = max(dow_counts.values(), default=1)
    lines.append("### Sessions by Day of Week")
    lines.append("| Day | Count | Activity |")
    lines.append("|-----|-------|----------|")
    for i, name in enumerate(day_names):
        cnt = dow_counts.get(i, 0)
        lines.append(f"| {name} | {cnt} | {_bar(cnt, max_dow)} |")
    lines.append("")

    # Mermaid bar chart: sessions by hour of day
    lines.append("```mermaid")
    lines.append("xychart-beta")
    lines.append('    title "Sessions by Hour of Day"')
    hour_labels = [f'"{h:02d}h"' for h in range(24)]
    hour_values = [str(hour_counts.get(h, 0)) for h in range(24)]
    lines.append(f'    x-axis [{", ".join(hour_labels)}]')
    lines.append(f'    bar [{", ".join(hour_values)}]')
    lines.append("```")
    lines.append("")

    max_hour = max(hour_counts.values(), default=1)
    lines.append("### Sessions by Hour of Day")
    lines.append("| Hour | Count | Activity |")
    lines.append("|------|-------|----------|")
    for h in range(24):
        cnt = hour_counts.get(h, 0)
        lines.append(f"| {h:02d} | {cnt} | {_bar(cnt, max_hour)} |")
    lines.append("")

    # Weekly Activity Trend
    lines.append("## Weekly Activity Trend")
    lines.append("")
    week_data: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "cost": 0.0, "tokens": 0})
    for s in all_sessions:
        if s.start_time:
            week = _iso_week(s.start_time)
            week_data[week]["sessions"] += 1
            week_data[week]["cost"] += s.cost_usd
            week_data[week]["tokens"] += s.total_tokens()

    sorted_weeks = sorted(week_data.keys())

    # Short labels: strip year prefix, keep only "Wnn" to avoid overlap
    short_week_labels = [f'"{w.split("-")[1]}"' for w in sorted_weeks]
    week_costs = [f"{week_data[w]['cost']:.2f}" for w in sorted_weeks]
    week_session_counts = [str(week_data[w]["sessions"]) for w in sorted_weeks]

    # Mermaid line chart: weekly cost trend
    lines.append("```mermaid")
    lines.append("xychart-beta")
    lines.append('    title "Weekly Spend ($)"')
    lines.append(f'    x-axis [{", ".join(short_week_labels)}]')
    lines.append(f'    line [{", ".join(week_costs)}]')
    lines.append("```")
    lines.append("")

    # Mermaid bar chart: weekly sessions
    lines.append("```mermaid")
    lines.append("xychart-beta")
    lines.append('    title "Weekly Sessions Count"')
    lines.append(f'    x-axis [{", ".join(short_week_labels)}]')
    lines.append(f'    bar [{", ".join(week_session_counts)}]')
    lines.append("```")
    lines.append("")

    max_week_cost = max((v["cost"] for v in week_data.values()), default=1)
    lines.append("| Week | Sessions | Cost | Tokens | Spend Bar |")
    lines.append("|------|----------|------|--------|-----------|")
    for week in sorted_weeks:
        wd = week_data[week]
        lines.append(
            f"| {week} | {wd['sessions']} | ${wd['cost']:.2f} "
            f"| {format_tokens(wd['tokens'])} | {_bar(wd['cost'], max_week_cost)} |"
        )
    lines.append("")

    # Code Productivity
    sessions_with_git = [s for s in all_sessions if s.lines_added > 0 or s.lines_removed > 0]
    if sessions_with_git:
        total_added = sum(s.lines_added for s in sessions_with_git)
        total_removed = sum(s.lines_removed for s in sessions_with_git)
        total_lines = total_added + total_removed
        git_cost = sum(s.cost_usd for s in sessions_with_git)
        lines_per_dollar = total_lines / git_cost if git_cost > 0 else 0
        git_tokens = sum(s.total_tokens() for s in sessions_with_git)
        lines_per_1k = total_lines / (git_tokens / 1000) if git_tokens > 0 else 0

        lines.append("## Code Productivity")
        lines.append("")
        lines.append(f"> Based on {len(sessions_with_git)} sessions with git activity data.")
        lines.append("")
        lines.append(
            f"- **Total lines changed**: {total_lines:,} (+{total_added:,} / -{total_removed:,})"
        )
        lines.append(f"- **Lines per dollar**: {int(lines_per_dollar)} lines/$")
        lines.append(f"- **Lines per 1k tokens**: {lines_per_1k:.1f} lines/1k tokens")
        lines.append("")

        # Top 5 projects by lines/$ efficiency
        proj_git: dict[str, dict] = defaultdict(lambda: {"lines": 0, "cost": 0.0})
        for s in sessions_with_git:
            proj_git[s.project_dir]["lines"] += s.lines_added + s.lines_removed
            proj_git[s.project_dir]["cost"] += s.cost_usd
        top_efficient_proj = sorted(
            proj_git.items(),
            key=lambda kv: kv[1]["lines"] / kv[1]["cost"] if kv[1]["cost"] > 0 else 0,
            reverse=True,
        )[:5]
        lines.append("### Top 5 Projects by Lines/$ Efficiency")
        lines.append("| Project | Lines Changed | Cost | Lines/$ |")
        lines.append("|---------|--------------|------|---------|")
        for proj_dir, pd in top_efficient_proj:
            proj_name = proj_dir.split("/")[-1] if "/" in proj_dir else proj_dir
            eff = int(pd["lines"] / pd["cost"]) if pd["cost"] > 0 else 0
            lines.append(
                f"| {proj_name} | {pd['lines']:,} | ${pd['cost']:.2f} | {eff} |"
            )
        lines.append("")

    # Projects summary table
    lines.append("## Projects")
    lines.append("")
    lines.append(
        "| # | Project | Sessions | Cost | % Total | Tokens | Cache Hit % | Avg Cost | Dominant Model |"
    )
    lines.append("|---|---------|----------|------|---------|--------|-------------|----------|----------------|")
    for idx, p in enumerate(projects_stats, 1):
        pct = p.cost_usd / total_cost * 100 if total_cost > 0 else 0
        avg_cost = p.cost_usd / p.session_count if p.session_count > 0 else 0
        lines.append(
            f"| {idx} | {p.project_name()} | {p.session_count} | ${p.cost_usd:.2f} "
            f"| {pct:.1f}% | {format_tokens(p.total_tokens())} "
            f"| {p.cache_hit_ratio():.1f}% | ${avg_cost:.2f} | {p.dominant_model()} |"
        )
    lines.append("")

    lines.append("---")
    lines.append("*Report generated by cc-context-stats*")

    return "\n".join(lines)


def run_report(argv: list[str]) -> None:
    """Execute report command."""
    args = _parse_report_args(argv)

    projects_stats = load_all_projects(since_days=args.since_days)

    if not projects_stats:
        print("No project data found in ~/.claude/statusline/", file=sys.stderr)
        sys.exit(1)

    report = generate_report(projects_stats)

    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = Path.cwd() / f"context-stats-report-{timestamp}.md"

    try:
        with open(output_path, "w") as f:
            f.write(report)
        print(f"✓ Report generated: {output_path}")
    except OSError as e:
        print(f"✗ Failed to write report: {e}", file=sys.stderr)
        sys.exit(1)
