"""Export command — generates a markdown report of session context stats.

Usage:
    context-stats export [session_id] [--output FILE]

Reads the CSV state history for a session and produces a well-formatted
markdown file with per-interaction token usage, MI scores, and trends.
"""

from __future__ import annotations

import argparse
import sys
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
        "--output", "-o",
        default=None,
        help="Output file path (default: context-stats-<session>.md)",
    )
    return parser.parse_args(argv)


def _format_datetime(ts: int) -> str:
    """Format Unix timestamp as full datetime string."""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return str(ts)


def _format_time(ts: int) -> str:
    """Format Unix timestamp as time-only string."""
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except (ValueError, OSError):
        return str(ts)


def _format_duration(seconds: int) -> str:
    """Format duration in seconds."""
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

    lines.append(f"# Context Stats Report")
    lines.append("")
    lines.append(f"**Session:** `{session_id}`")
    lines.append(f"**Project:** {project_name}")
    lines.append(f"**Model:** {last.model_id or 'Unknown'}")
    lines.append(f"**Duration:** {_format_duration(duration)} ({start_time} \u2192 {end_time})")
    lines.append(f"**Interactions:** {len(entries)}")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} by cc-context-stats v{__version__}")
    lines.append("")

    # --- Summary ---
    lines.append("## Summary")
    lines.append("")

    ctx_window = last.context_window_size
    final_used = last.current_used_tokens
    final_pct = (final_used / ctx_window * 100) if ctx_window > 0 else 0

    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Context window | {format_tokens(ctx_window)} tokens |")
    lines.append(f"| Final usage | {format_tokens(final_used)} ({final_pct:.1f}%) |")
    lines.append(f"| Total input tokens | {format_tokens(last.total_input_tokens)} |")
    lines.append(f"| Total output tokens | {format_tokens(last.total_output_tokens)} |")

    if last.cost_usd > 0:
        lines.append(f"| Session cost | ${last.cost_usd:.4f} |")

    if last.lines_added or last.lines_removed:
        lines.append(f"| Lines changed | +{last.lines_added} / -{last.lines_removed} |")

    # MI score
    beta = config.mi_curve_beta
    mi = calculate_intelligence(last, ctx_window, last.model_id, beta)
    zone = get_context_zone(final_used, ctx_window)
    lines.append(f"| Final MI score | {mi.mi:.3f} ({zone.label}) |")
    lines.append("")

    # --- Usage bar ---
    lines.append(f"**Context usage:** `{_usage_bar(final_pct)}` {final_pct:.1f}%")
    lines.append("")

    # --- Interaction Timeline ---
    lines.append("## Interaction Timeline")
    lines.append("")
    lines.append("| # | Time | Input (req) | Output (req) | Context Used | Usage % | MI | Zone |")
    lines.append("|---|------|-------------|--------------|--------------|---------|------|------|")

    for i, entry in enumerate(entries, 1):
        time_str = _format_time(entry.timestamp)
        ctx_used = entry.current_used_tokens
        ctx_pct = (ctx_used / entry.context_window_size * 100) if entry.context_window_size > 0 else 0
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
    lines.append(f"- **Total growth:** {format_tokens(last.current_used_tokens - entries[0].current_used_tokens)} tokens")
    if max_delta > 0 and max_delta_idx < len(entries):
        lines.append(f"- **Largest single jump:** {format_tokens(max_delta)} tokens (interaction #{max_delta_idx + 1})")
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
    lines.append(f"*Generated by [cc-context-stats](https://github.com/luongnv89/cc-context-stats) v{__version__}*")
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
        session_id = name.replace("statusline.", "")

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
