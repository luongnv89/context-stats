"""Export command — generates a markdown report of session context stats.

Usage:
    context-stats export [session_id] [--output FILE]

Reads the CSV state history for a session and produces a well-formatted
markdown file with per-interaction token usage, MI scores, and trends.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from claude_statusline import __version__
from claude_statusline.core.config import Config
from claude_statusline.core.state import StateFile, _validate_session_id
from claude_statusline.formatters.tokens import format_tokens
from claude_statusline.graphs.intelligence import (
    calculate_intelligence,
    get_context_zone,
)


def _parse_export_args(argv: list[str]) -> argparse.Namespace:
    """Parse export subcommand arguments.

    Args:
        argv: Argument list (after 'export' keyword).

    Returns:
        Parsed namespace with session_id and output.
    """
    parser = argparse.ArgumentParser(
        prog="context-stats export",
        description="Export session context stats as markdown",
    )
    parser.add_argument(
        "session_id",
        nargs="?",
        default=None,
        help="Session ID (default: latest session)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file path (default: context-stats-<session>.md)",
    )
    return parser.parse_args(argv)


def _format_datetime(ts: int) -> str:
    """Format Unix timestamp as full datetime string."""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return str(ts)


def _format_time(ts: int) -> str:
    """Format Unix timestamp as time-only string."""
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return str(ts)


def _format_duration(seconds: int) -> str:
    """Format duration in seconds."""
    seconds = max(0, seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _usage_bar(pct: float, width: int = 20) -> str:
    """Generate a text-based usage bar.

    Args:
        pct: Percentage (0-100).
        width: Bar width in characters.

    Returns:
        Bar string like '████████░░░░░░░░░░░░'
    """
    filled = int(pct / 100 * width)
    filled = max(0, min(width, filled))
    return "\u2588" * filled + "\u2591" * (width - filled)


def _format_chart_timestamp(ts: int) -> str:
    """Format Unix timestamp for compact chart axis labels."""
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M")
    except (ValueError, OSError, OverflowError):
        return str(ts)


def _sample_entries_by_window(
    entries: list, window_minutes: int = 5, max_points: int = 12
) -> list[tuple[str, object]]:
    """Downsample entries so Mermaid charts stay readable on long sessions.

    Keep at most one point per time window, then trim again if the chart is
    still too dense.
    """
    if not entries:
        return []

    window_seconds = max(1, window_minutes) * 60
    sampled: list[tuple[str, object]] = [
        (_format_chart_timestamp(entries[0].timestamp), entries[0])
    ]
    last_kept_ts = entries[0].timestamp

    for entry in entries[1:-1]:
        if entry.timestamp - last_kept_ts >= window_seconds:
            sampled.append((_format_chart_timestamp(entry.timestamp), entry))
            last_kept_ts = entry.timestamp

    if len(entries) > 1:
        last_label = _format_chart_timestamp(entries[-1].timestamp)
        if sampled[-1][1] is not entries[-1]:
            sampled.append((last_label, entries[-1]))

    if len(sampled) <= max_points:
        return sampled

    step = (len(sampled) - 1) / (max_points - 1)
    reduced: list[tuple[str, object]] = []
    seen: set[int] = set()
    for i in range(max_points):
        index = round(i * step)
        if index in seen:
            continue
        seen.add(index)
        reduced.append(sampled[index])
    return reduced


def _nice_axis_max(value: int) -> int:
    """Round an axis maximum up to a clean chart boundary."""
    if value <= 1_000:
        step = 100
    elif value <= 10_000:
        step = 1_000
    elif value <= 100_000:
        step = 5_000
    elif value <= 500_000:
        step = 10_000
    else:
        step = 50_000
    return ((max(1, value) + step - 1) // step) * step


def _generate_mermaid_trend_chart(entries: list, context_window: int) -> list[str]:
    """Generate a Mermaid xychart showing context usage over time."""
    sampled = _sample_entries_by_window(entries, window_minutes=15, max_points=10)
    x_values = ", ".join(f'"{label}"' for label, _ in sampled)
    y_values = ", ".join(str(entry.current_used_tokens) for _, entry in sampled)
    max_used = max((entry.current_used_tokens for _, entry in sampled), default=0)
    y_max = _nice_axis_max(max(context_window, max_used))

    return [
        "### Context Trend",
        "",
        "Shows how much context was used at each sampled point so you can spot growth, resets, and sudden jumps.",
        "",
        "```mermaid",
        '%%{init: {"theme": "base", "themeVariables": {"xyChart": {"plotColorPalette": "#2563eb"}}}}%%',
        "xychart-beta",
        '    title "Context Used Over Time"',
        f"    x-axis [{x_values}]",
        f'    y-axis "Tokens" 0 --> {y_max}',
        f"    line [{y_values}]",
        "```",
        "",
    ]


def _generate_mermaid_zone_chart(entries: list, context_window: int) -> list[str]:
    """Generate a Mermaid pie chart showing how often each zone appears."""
    zone_counts = Counter(
        get_context_zone(entry.current_used_tokens, context_window).label for entry in entries
    )

    lines = [
        "### Zone Distribution",
        "",
        "Shows where the session spent most of its time relative to the context window, which highlights whether the conversation stayed in a safe range or drifted into heavier usage.",
        "",
        "```mermaid",
        "pie showData",
        '    title "Interaction Distribution by Zone"',
    ]
    for label, count in sorted(zone_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f'    "{label}" : {count}')
    lines.extend(["```", ""])
    return lines


def _generate_mermaid_composition_chart(last_entry) -> list[str]:
    """Generate a Mermaid pie chart for the final context composition."""
    parts = {
        "Input tokens": last_entry.current_input_tokens,
        "Cache creation": last_entry.cache_creation,
        "Cache read": last_entry.cache_read,
    }

    non_zero_parts = {label: value for label, value in parts.items() if value > 0}
    if not non_zero_parts:
        non_zero_parts = {"Input tokens": 1}

    lines = [
        "### Final Context Composition",
        "",
        "Shows what made up the last request in the session, which helps explain whether the final context was mostly fresh input, cache reuse, or newly created cache.",
        "",
        "```mermaid",
        "pie showData",
        '    title "Final Context Usage Breakdown"',
    ]
    for label, value in sorted(non_zero_parts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f'    "{label}" : {value}')
    lines.extend(["```", ""])
    return lines


def _generate_mermaid_cache_chart(entries: list) -> list[str]:
    """Generate a Mermaid xychart showing cache creation and cache read over time."""
    sampled = _sample_entries_by_window(entries, window_minutes=10, max_points=12)
    creation_values = [entry.cache_creation for _, entry in sampled]
    read_values = [entry.cache_read for _, entry in sampled]
    max_cache = max((*creation_values, *read_values), default=0)

    if max_cache <= 0:
        return []

    x_values = ", ".join(f'"{label}"' for label, _ in sampled)
    creation_series = ", ".join(str(value) for value in creation_values)
    read_series = ", ".join(str(value) for value in read_values)
    y_max = _nice_axis_max(max_cache)

    return [
        "### Cache Activity Trend",
        "",
        "Shows how cache creation and cache reads evolved over time so you can see when the session started reusing previous work versus building new cache.",
        "",
        "```mermaid",
        '%%{init: {"theme": "base", "themeVariables": {"xyChart": {"plotColorPalette": "#2563eb, #f97316"}}}}%%',
        "xychart-beta",
        '    title "Cache Created vs Cache Read Over Time"',
        f"    x-axis [{x_values}]",
        f'    y-axis "Tokens" 0 --> {y_max}',
        f"    line [{creation_series}]",
        f"    line [{read_series}]",
        "```",
        "",
        "- Legend: blue line = `Cache creation`, orange line = `Cache read`.",
        "",
    ]


def _generate_key_takeaways(
    entries: list,
    last_entry,
    ctx_window: int,
    final_used: int,
    final_pct: float,
    zone_label: str,
    duration: int,
) -> list[str]:
    """Generate a compact bullet list of the main insights from the session."""
    prev_used = 0
    max_delta = 0
    max_delta_idx = 0
    for i, entry in enumerate(entries):
        ctx_used = entry.current_used_tokens
        delta = ctx_used - prev_used
        if abs(delta) > max_delta:
            max_delta = abs(delta)
            max_delta_idx = i
        prev_used = ctx_used

    zones = Counter(
        get_context_zone(entry.current_used_tokens, ctx_window).label for entry in entries
    )
    dominant_zone, dominant_zone_count = zones.most_common(1)[0]
    cache_total = last_entry.cache_creation + last_entry.cache_read
    cache_ratio = (cache_total / final_used * 100) if final_used > 0 else 0
    growth = final_used - entries[0].current_used_tokens
    growth_pct = (growth / ctx_window * 100) if ctx_window > 0 else 0

    takeaways = [
        f"- **Final state:** {format_tokens(final_used)} used ({final_pct:.1f}%) and currently in the **{zone_label}**.",
        f"- **Growth:** context increased by {format_tokens(growth)} tokens over {_format_duration(duration)} ({growth_pct:.1f}% of the window).",
        f"- **Largest jump:** {format_tokens(max_delta)} tokens at interaction #{max_delta_idx + 1}.",
        f"- **Dominant zone:** **{dominant_zone}** for {dominant_zone_count} of {len(entries)} interactions.",
    ]

    if cache_total > 0:
        takeaways.append(
            f"- **Cache load:** {format_tokens(cache_total)} tokens in cache activity ({cache_ratio:.1f}% of the final used context)."
        )
        if last_entry.cache_creation >= last_entry.cache_read:
            takeaways.append(
                "- **Cache pattern:** more cache creation than cache reads, so the session leaned toward new cache material."
            )
        else:
            takeaways.append(
                "- **Cache pattern:** cache reads outweighed creation, so the session reused prior work heavily."
            )

    return takeaways


def _generate_exec_snapshot(
    session_id: str,
    project_name: str,
    last_entry,
    ctx_window: int,
    final_used: int,
    final_pct: float,
    zone_label: str,
    duration: int,
    start_time: str,
    end_time: str,
    interactions: int,
    zone_recommendation: str = "",
) -> list[str]:
    """Generate a compact executive snapshot for the top of the report."""
    cache_total = last_entry.cache_creation + last_entry.cache_read
    cache_pct = (cache_total / final_used * 100) if final_used > 0 else 0
    lines = [
        "## Executive Snapshot",
        "",
        "| Signal | Value | Why it matters |",
        "|--------|-------|----------------|",
        f"| **Session** | `{session_id}` | Lets you link this export back to the source interaction stream. |",
        f"| **Project** | **{project_name}** | Identifies where the report came from. |",
        f"| **Model** | **{last_entry.model_id or 'Unknown'}** | Shows which model produced the session. |",
        f"| **Duration** | **{_format_duration(duration)}** | Helps you relate context growth to session length. |",
        f"| **Report span** | **{start_time} -> {end_time}** | Gives the exact time range covered by the export. |",
        f"| **Interactions** | **{interactions}** | Shows how active the session was overall. |",
        f"| **Produced by** | **context-stats v{__version__}** | Shows which tool generated the report. |",
        f"| **Generated** | **{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}** | Records when the report was produced. |",
        f"| **Final usage** | **{format_tokens(final_used)}** ({final_pct:.1f}%) | Shows how close the session ended to the context limit. |",
        f"| **Final zone** | **{zone_label}** | Indicates whether the session stayed in a safe working range. |",
    ]
    if zone_recommendation:
        lines.append(
            f"| **Recommendation** | {zone_recommendation} | Suggested next action based on context zone. |"
        )

    if cache_total > 0:
        lines.append(
            f"| **Cache activity** | **{format_tokens(cache_total)}** ({cache_pct:.1f}%) | Explains how much of the final context is cache-related. |"
        )

    lines.append("")
    return lines


def _generate_markdown(entries: list, session_id: str, config: Config) -> str:
    """Generate the markdown report content.

    Args:
        entries: List of StateEntry objects.
        session_id: Session identifier.
        config: Configuration object.

    Returns:
        Markdown string.
    """
    lines: list[str] = []

    # --- Header ---
    first = entries[0]
    last = entries[-1]
    start_time = _format_datetime(first.timestamp)
    end_time = _format_datetime(last.timestamp)
    duration = last.timestamp - first.timestamp

    project = last.workspace_project_dir
    if project:
        project_name = Path(project).name
    else:
        project_name = "Unknown"

    lines.append("# Context Stats Report")
    lines.append("")

    ctx_window = last.context_window_size
    final_used = last.current_used_tokens
    final_pct = (final_used / ctx_window * 100) if ctx_window > 0 else 0
    beta = config.mi_curve_beta
    mi = calculate_intelligence(last, ctx_window, last.model_id, beta)
    zone = get_context_zone(final_used, ctx_window)

    lines.append("## Generate")
    lines.append("")
    lines.append("```bash")
    lines.append(f"context-stats export {session_id} --output report.md")
    lines.append("```")
    lines.append("")

    exec_snapshot = _generate_exec_snapshot(
        session_id,
        project_name,
        last,
        ctx_window,
        final_used,
        final_pct,
        zone.label,
        duration,
        start_time,
        end_time,
        len(entries),
        zone_recommendation=zone.recommendation,
    )
    lines.extend(exec_snapshot)

    # --- Summary ---
    lines.append("## Summary")
    lines.append("")

    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Context window | {format_tokens(ctx_window)} tokens |")
    lines.append(f"| Final usage | {format_tokens(final_used)} ({final_pct:.1f}%) |")
    lines.append(f"| Total input tokens | {format_tokens(last.total_input_tokens)} |")
    lines.append(f"| Total output tokens | {format_tokens(last.total_output_tokens)} |")

    if last.cost_usd > 0:
        lines.append(f"| Session cost | ${last.cost_usd:.4f} |")

    if last.lines_added or last.lines_removed:
        lines.append(f"| Lines changed | +{last.lines_added} / -{last.lines_removed} |")

    lines.append(f"| Final MI score | {mi.mi:.3f} ({zone.label}) |")
    lines.append("")

    # --- Usage bar ---
    lines.append("### Context Usage")
    lines.append("")
    lines.append(f"**Context usage:** `{_usage_bar(final_pct)}` {final_pct:.1f}%")
    lines.append("")

    # --- Key Takeaways ---
    lines.append("## Key Takeaways")
    lines.append("")
    lines.extend(
        _generate_key_takeaways(
            entries, last, ctx_window, final_used, final_pct, zone.label, duration
        )
    )
    lines.append("")

    # --- Mermaid Visual Summary ---
    lines.append("## Visual Summary")
    lines.append("")
    lines.extend(_generate_mermaid_trend_chart(entries, ctx_window))
    lines.extend(_generate_mermaid_zone_chart(entries, ctx_window))
    lines.extend(_generate_mermaid_composition_chart(last))
    cache_chart = _generate_mermaid_cache_chart(entries)
    if cache_chart:
        lines.extend(cache_chart)

    # --- Interaction Timeline ---
    lines.append("## Interaction Timeline")
    lines.append("")
    lines.append("| # | Time | Input (req) | Output (req) | Context Used | Usage % | MI | Zone |")
    lines.append("|---|------|-------------|--------------|--------------|---------|------|------|")

    for i, entry in enumerate(entries, 1):
        time_str = _format_time(entry.timestamp)
        ctx_used = entry.current_used_tokens
        ctx_pct = (
            (ctx_used / entry.context_window_size * 100) if entry.context_window_size > 0 else 0
        )
        mi_score = calculate_intelligence(entry, entry.context_window_size, entry.model_id, beta)
        zone_info = get_context_zone(ctx_used, entry.context_window_size)

        lines.append(
            f"| {i} "
            f"| {time_str} "
            f"| {format_tokens(entry.current_input_tokens)} "
            f"| {format_tokens(entry.current_output_tokens)} "
            f"| {format_tokens(ctx_used)} "
            f"| {ctx_pct:.1f}% "
            f"| {mi_score.mi:.3f} "
            f"| {zone_info.zone} |"
        )

    lines.append("")

    # --- Context Growth ---
    lines.append("## Context Growth")
    lines.append("")

    prev_used = 0
    max_delta = 0
    max_delta_idx = 0
    for i, entry in enumerate(entries):
        ctx_used = entry.current_used_tokens
        delta = ctx_used - prev_used
        if abs(delta) > max_delta:
            max_delta = abs(delta)
            max_delta_idx = i
        prev_used = ctx_used

    lines.append(f"- **Starting context:** {format_tokens(entries[0].current_used_tokens)} tokens")
    lines.append(f"- **Final context:** {format_tokens(last.current_used_tokens)} tokens")
    lines.append(
        f"- **Total growth:** {format_tokens(last.current_used_tokens - entries[0].current_used_tokens)} tokens"
    )
    if max_delta > 0 and max_delta_idx < len(entries):
        lines.append(
            f"- **Largest single jump:** {format_tokens(max_delta)} tokens (interaction #{max_delta_idx + 1})"
        )
    lines.append("")

    # --- Token Breakdown ---
    if any(e.cache_creation > 0 or e.cache_read > 0 for e in entries):
        lines.append("## Cache Statistics")
        lines.append("")
        lines.append("| # | Time | Cache Create | Cache Read |")
        lines.append("|---|------|--------------|------------|")
        for i, entry in enumerate(entries, 1):
            if entry.cache_creation > 0 or entry.cache_read > 0:
                time_str = _format_time(entry.timestamp)
                lines.append(
                    f"| {i} "
                    f"| {time_str} "
                    f"| {format_tokens(entry.cache_creation)} "
                    f"| {format_tokens(entry.cache_read)} |"
                )
        lines.append("")

    # --- Footer ---
    lines.append("---")
    lines.append(
        f"*Generated by [context-stats](https://github.com/luongnv89/cc-context-stats) v{__version__}*"
    )
    lines.append("")

    return "\n".join(lines)


def run_export(argv: list[str]) -> None:
    """Run the export command.

    Args:
        argv: Arguments after 'export' keyword.
    """
    args = _parse_export_args(argv)

    # Validate session ID
    if args.session_id is not None:
        try:
            _validate_session_id(args.session_id)
        except ValueError as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.exit(1)

    # Load config
    config = Config.load()

    # Find state file
    state_file = StateFile(args.session_id)
    file_path = state_file.find_latest_state_file()

    if not file_path or not file_path.exists():
        if args.session_id:
            sys.stderr.write(f"Error: No state file found for session '{args.session_id}'\n")
            sys.stderr.write("  Available sessions:\n")
            for sid in sorted(state_file.list_sessions())[-10:]:
                sys.stderr.write(f"    {sid}\n")
        else:
            sys.stderr.write("Error: No session data found.\n")
            sys.stderr.write("  Run Claude Code to generate token usage data.\n")
        sys.exit(1)

    # Read history
    entries = state_file.read_history()
    if not entries:
        sys.stderr.write("Error: State file is empty — no data to export.\n")
        sys.exit(1)

    # Determine session ID (might have been auto-detected)
    session_id = args.session_id
    if not session_id:
        name = file_path.stem  # statusline.{session_id}
        session_id = name.removeprefix("statusline.")

    # Generate markdown
    markdown = _generate_markdown(entries, session_id, config)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        # Shorten session ID for filename
        short_id = session_id[:8] if len(session_id) > 8 else session_id
        output_path = Path.cwd() / f"context-stats-{short_id}.md"

    # Write file
    try:
        output_path.write_text(markdown, encoding="utf-8")
    except OSError as e:
        sys.stderr.write(f"Error: Failed to write {output_path}: {e}\n")
        sys.exit(1)

    print(f"Exported to {output_path}")
    print(f"  Session: {session_id}")
    print(f"  Interactions: {len(entries)}")
    print(f"  Model: {entries[-1].model_id or 'Unknown'}")
