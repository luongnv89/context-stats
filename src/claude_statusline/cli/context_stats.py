#!/usr/bin/env python3
"""Context Stats Visualizer for Claude Code.

Displays ASCII graphs of token consumption over time.

Usage:
    context-stats [session_id] [action] [parameters]

When session_id is omitted, the most recent session is used automatically.
When action is omitted, defaults to 'graph'.

Actions:
    graph       Live ASCII graphs of context usage (default)
    export      Export session stats as a markdown report
    sessions    List recent sessions
    explain     Diagnostic dump of Claude Code's JSON context (pipe JSON to stdin)
    cache-warm  Keep session prompt cache alive via a background heartbeat

Options:
    --type <cumulative|delta|io|both|all>  Graph type to display (default: delta)
    --watch, -w [interval]                  Real-time monitoring mode (default: 2s)
    --no-color                              Disable color output
    --version, -V                           Show version and exit
    --help                                  Show this help
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from claude_statusline import __version__
from claude_statusline.core.colors import ColorManager
from claude_statusline.core.config import Config
from claude_statusline.core.state import StateFile, _validate_session_id
from claude_statusline.graphs.renderer import GraphDimensions, GraphRenderer
from claude_statusline.graphs.statistics import calculate_deltas, detect_compaction_events
from claude_statusline.ui.icons import get_activity_tier, get_tier_label
from claude_statusline.ui.waiting import get_waiting_text, is_active

# Cursor control sequences
CURSOR_HOME = "\033[H"
CLEAR_SCREEN = "\033[2J"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_TO_END = "\033[J"


def show_help() -> None:
    """Show help message."""
    print(
        """Context Stats Visualizer for Claude Code

USAGE:
    context-stats [session_id] [action] [parameters]

    When session_id is omitted, the most recent session is used automatically.
    When action is omitted, defaults to 'graph'.

ARGUMENTS:
    session_id    Optional. The session ID to operate on (default: latest).
    action        Optional. The action to perform (default: graph).

ACTIONS:
    graph         Show live ASCII graphs of context usage
    export        Export session stats as a markdown report
    sessions      List recent sessions (default: last 5 minutes)
    explain       Diagnostic dump of Claude Code's JSON context (pipe JSON to stdin)
    cache-warm    Keep session prompt cache alive via a background heartbeat
    report        Generate comprehensive token usage analytics across all projects

SESSIONS OPTIONS:
    --minutes N    Show sessions from the last N minutes (default: 5)

CACHE-WARM OPTIONS:
    on [duration]  Start heartbeat for the given duration (e.g. 30m, 1h). Default: 30m
    off            Stop an active heartbeat immediately

GRAPH OPTIONS:
    --type <type>  Graph type to display:
                   - delta: Context growth per interaction (default)
                   - cumulative: Total context usage over time
                   - io: Input/output tokens over time
                   - cache: Cache creation/read tokens over time
                   - mi: Model Intelligence score over time
                   - both: Show cumulative and delta graphs
                   - all: Show all graphs including I/O, cache, and MI
    -w [interval]  Set refresh interval in seconds (default: 2)
    --no-watch     Show graphs once and exit (disable live monitoring)

EXPORT OPTIONS:
    --output FILE  Output file path (default: context-stats-<session>.md)

GLOBAL OPTIONS:
    --no-color     Disable color output
    --version, -V  Show version and exit
    --help         Show this help message

NOTE:
    By default, graph action runs in live monitoring mode, refreshing every 2 seconds.
    Press Ctrl+C to exit. Use --no-watch to display graphs once and exit.

EXAMPLES:
    # Show live graphs for the latest session (no session ID needed)
    context-stats graph

    # Show live graphs for a specific session
    context-stats abc123def graph

    # Shorthand: just run with no arguments for latest session graphs
    context-stats

    # List recent sessions (last 5 minutes)
    context-stats sessions

    # List sessions from the last 30 minutes
    context-stats sessions --minutes 30

    # Show graphs once and exit
    context-stats abc123def graph --no-watch

    # Show only cumulative graph
    context-stats abc123def graph --type cumulative

    # Show graphs with custom refresh interval
    context-stats abc123def graph -w 5

    # Export session stats as markdown
    context-stats abc123def export --output report.md

    # Export latest session stats
    context-stats export

    # Diagnostic dump (pipe Claude Code JSON context)
    echo '{"model":{"display_name":"Opus"},...}' | context-stats explain

    # Start cache-warm heartbeat for 30 minutes
    context-stats abc123def cache-warm on 30m

    # Stop an active cache-warm heartbeat
    context-stats abc123def cache-warm off

    # Output to file (no colors, single run)
    context-stats abc123def graph --no-watch --no-color > output.txt

    # Generate comprehensive analytics report for all projects
    context-stats report

    # Generate report with output file specified
    context-stats report --output my-report.md

    # Generate report for last 30 days
    context-stats report --since-days 30

DATA SOURCE:
    Reads token history from ~/.claude/statusline/statusline.<session_id>.state
"""
    )


# Known action names — used to distinguish actions from session IDs in argv
_KNOWN_ACTIONS = {"graph", "export", "explain", "cache-warm", "report", "sessions"}


def _normalize_argv(argv: list[str]) -> tuple[str, str | None, list[str]]:
    """Determine action, session_id, and remaining args from raw argv.

    Supported patterns:
      context-stats                           → graph, latest session
      context-stats <action> [parameters]     → action, latest session
      context-stats <session_id>              → graph, specific session
      context-stats <session_id> <action>     → action, specific session

    Session_id is None when omitted (auto-detect latest).
    Explain uses '-' as a placeholder session_id.

    Args:
        argv: sys.argv[1:] (arguments after the program name).

    Returns:
        Tuple of (action, session_id | None, remaining_args).

    Raises:
        SystemExit: If an unknown action is specified.
    """
    # Strip out global flags so they don't interfere with positional detection
    positionals = [a for a in argv if not a.startswith("-")]

    if not positionals:
        # No arguments at all: default to graph with latest session
        remaining = [a for a in argv if a.startswith("-")]
        return "graph", None, remaining

    # First positional is a known action: no session_id provided
    if positionals[0] in _KNOWN_ACTIONS:
        action = positionals[0]
        remaining = list(argv)
        remaining.remove(action)
        # explain historically used "-" placeholder; keep for explain
        if action == "explain":
            return action, "-", remaining
        return action, None, remaining

    # First positional is not a known action: treat as session_id
    session_id = positionals[0]

    if len(positionals) < 2:
        # Single positional that is not a known action: treat as session_id, default to graph
        remaining = list(argv)
        remaining.remove(session_id)
        return "graph", session_id, remaining

    action = positionals[1]

    if action not in _KNOWN_ACTIONS:
        sys.stderr.write(
            f"Error: Unknown action '{action}'. Valid actions: {', '.join(sorted(_KNOWN_ACTIONS))}\n"
        )
        sys.exit(1)

    # Build remaining args: remove session_id and action from argv
    remaining = list(argv)
    remaining.remove(session_id)
    remaining.remove(action)

    return action, session_id, remaining


def _build_graph_parser() -> argparse.ArgumentParser:
    """Build argument parser for the graph action."""
    parser = argparse.ArgumentParser(
        prog="context-stats graph",
        description="Show live ASCII graphs of context usage",
        add_help=False,
    )
    parser.add_argument("session_id", nargs="?", default=None, help="Session ID")
    parser.add_argument(
        "--type",
        choices=["cumulative", "delta", "io", "cache", "mi", "both", "all"],
        default="delta",
        help="Graph type (default: delta)",
    )
    parser.add_argument(
        "--watch",
        "-w",
        nargs="?",
        const=2,
        type=int,
        default=2,
        help="Refresh interval in seconds (default: 2)",
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="Show graphs once and exit",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable color output",
    )
    parser.add_argument(
        "--help",
        "-h",
        action="store_true",
        help="Show help for graph action",
    )
    return parser


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments using action-based dispatch."""
    # Top-level flags handled before action dispatch
    raw_argv = sys.argv[1:]

    if "--version" in raw_argv or "-V" in raw_argv:
        print(f"context-stats {__version__}")
        sys.exit(0)

    if not raw_argv or raw_argv == ["--help"] or raw_argv == ["-h"]:
        show_help()
        sys.exit(0)

    # Parse required session_id and action
    action, session_id, remaining = _normalize_argv(raw_argv)

    # Validate session_id format (skip for "-" placeholder and None/auto-detect)
    if session_id is not None and session_id != "-":
        try:
            _validate_session_id(session_id)
        except ValueError as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.exit(1)

    if action == "graph":
        # Inject session_id into remaining for graph parser (skip if None/auto-detect)
        remaining = ([session_id] if session_id is not None else []) + remaining
        parser = _build_graph_parser()
        args = parser.parse_args(remaining)
        if args.help:
            parser.print_help()
            sys.exit(0)
        args.action = "graph"
        return args

    # For export and explain, return minimal namespace; main() handles them
    args = argparse.Namespace(action=action, session_id=session_id, remaining=remaining)
    return args


def render_once(
    state_file: StateFile,
    graph_type: str,
    renderer: GraphRenderer,
    colors: ColorManager,
    watch_mode: bool = False,
    config: Config | None = None,
    cycle_index: int = 0,
) -> bool | str:
    """Render graphs once.

    Args:
        state_file: StateFile instance
        graph_type: Type of graphs to render
        renderer: GraphRenderer instance
        colors: ColorManager instance
        watch_mode: Whether running in watch mode
        config: Config instance for motion settings
        cycle_index: Watch mode refresh counter for rotating text

    Returns:
        True if rendering was successful (non-watch mode),
        buffered string if watch_mode is True,
        False if not enough data
    """
    entries = state_file.read_history()

    if len(entries) < 2:
        msg = (
            f"\n{colors.yellow}Need at least 2 data points to generate graphs.{colors.reset}\n"
            f"{colors.dim}Found: {len(entries)} entry. Use Claude Code to accumulate more data.{colors.reset}"
        )
        if watch_mode:
            return msg
        print(msg)
        return False

    # In watch mode, buffer all output
    lines: list[str] = []

    def emit(line: str = "") -> None:
        if watch_mode:
            lines.append(line)
        else:
            print(line)

    # Extract data for graphs
    timestamps = [e.timestamp for e in entries]
    # Current context window usage (what's actually in the context)
    # This is: cache_read + cache_creation + current_input_tokens
    context_used = [e.current_used_tokens for e in entries]
    # Per-request I/O tokens from current_usage
    current_input = [e.current_input_tokens for e in entries]
    current_output = [e.current_output_tokens for e in entries]
    cache_creation = [e.cache_creation for e in entries]
    cache_read_tokens = [e.cache_read for e in entries]
    deltas = calculate_deltas(context_used)
    delta_times = timestamps[1:]  # Deltas start from second entry

    # Get session name and project from entries
    file_path = state_file.find_latest_state_file()
    session_name = file_path.stem.removeprefix("statusline.") if file_path else "unknown"

    # Get project name from the last entry (most recent)
    last_entry = entries[-1]
    project_name = ""
    if last_entry.workspace_project_dir:
        # Extract just the project folder name from the path
        project_name = Path(last_entry.workspace_project_dir).name

    # Header
    if not watch_mode:
        emit()
    if project_name:
        emit(
            f"{colors.bold}{colors.magenta}Context Stats{colors.reset} "
            f"{colors.dim}({colors.cyan}{project_name}{colors.dim} • {session_name}){colors.reset}"
        )
    else:
        emit(
            f"{colors.bold}{colors.magenta}Context Stats{colors.reset} "
            f"{colors.dim}(Session: {session_name}){colors.reset}"
        )

    # Activity indicator (waiting text + label)
    reduced_motion = config.reduced_motion if config else False
    tier = get_activity_tier(entries, last_entry.context_window_size)
    label = get_tier_label(tier)
    active = is_active(entries)

    if active:
        text = get_waiting_text(cycle_index, reduced_motion)
        emit(f"  {colors.dim}{text} [{label}]{colors.reset}")
    else:
        emit(f"  {colors.dim}{label}{colors.reset}")

    # In watch mode, enable renderer buffering
    if watch_mode:
        renderer.begin_buffering()

    # Load config for compaction and MI settings
    mi_config = config if config else Config.load()

    # Detect compaction events upfront so markers are available for graph rendering
    compaction_indices = detect_compaction_events(context_used, mi_config.compaction_drop_threshold)

    # Render requested graphs
    if graph_type in ("cumulative", "both", "all"):
        renderer.render_timeseries(
            context_used,
            timestamps,
            "Context Usage Over Time",
            colors.green,
            compaction_indices=compaction_indices if compaction_indices else None,
        )

    if graph_type in ("delta", "both", "all"):
        renderer.render_timeseries(
            deltas, delta_times, "Context Growth Per Interaction", colors.cyan
        )

    if graph_type in ("io", "all"):
        renderer.render_timeseries(
            current_input, timestamps, "Input Tokens (per request)", colors.blue
        )
        renderer.render_timeseries(
            current_output, timestamps, "Output Tokens (per request)", colors.magenta
        )

    if graph_type in ("cache", "all"):
        renderer.render_timeseries(
            cache_creation, timestamps, "Cache Creation Tokens (per request)", colors.red
        )
        renderer.render_timeseries(
            cache_read_tokens, timestamps, "Cache Read Tokens (per request)", colors.cyan
        )

    # Compute MI scores for graph and/or summary
    mi_score = None
    if entries:
        from claude_statusline.graphs.intelligence import calculate_intelligence

        beta = mi_config.mi_curve_beta

        if graph_type in ("mi", "all"):
            # Compute MI for all entries (needed for timeseries graph)
            mi_scores = []
            for entry in entries:
                ctx_window = entry.context_window_size
                score = calculate_intelligence(entry, ctx_window, entry.model_id, beta)
                mi_scores.append(score)

            mi_score = mi_scores[-1]

            # Scale MI scores to [0, 10000] for integer renderer (3 decimal precision)
            mi_data = [int(s.mi * 10000) for s in mi_scores]
            renderer.render_timeseries(
                mi_data,
                timestamps,
                "Model Intelligence Over Time",
                colors.yellow,
                label_fn=lambda v: f"{v / 10000:.3f}",
            )
        else:
            # Only compute MI for last entry (for summary display)
            last = entries[-1]
            mi_score = calculate_intelligence(last, last.context_window_size, last.model_id, beta)

    # Compute MI at each compaction point for quality assessment (#65)
    compaction_events: list[tuple[int, float]] = []
    if compaction_indices and entries:
        from claude_statusline.graphs.intelligence import calculate_intelligence

        beta = mi_config.mi_curve_beta
        for ci in compaction_indices:
            if ci < len(entries):
                entry = entries[ci]
                score = calculate_intelligence(
                    entry, entry.context_window_size, entry.model_id, beta
                )
                compaction_events.append((ci, score.mi))

    # Summary and footer
    from claude_statusline.cli.cache_warm import _warm_state_path, is_cache_warm_active

    session_id = state_file.session_id or ""
    # Only show cache-warm status when a state file exists for this session
    cache_warm_status = (
        is_cache_warm_active(session_id)
        if session_id and _warm_state_path(session_id).exists()
        else None
    )
    renderer.render_summary(
        entries,
        deltas,
        mi_score=mi_score,
        graph_type=graph_type,
        cache_warm_status=cache_warm_status,
        compaction_events=compaction_events or None,
        compact_mi_warn_threshold=mi_config.compact_mi_warn_threshold,
    )
    renderer.render_footer(__version__)

    if watch_mode:
        # Collect renderer buffer and combine with header lines
        renderer_output = renderer.get_buffer()
        lines.append(renderer_output)
        return "\n".join(lines)

    return True


def run_watch_mode(
    state_file: StateFile,
    graph_type: str,
    interval: int,
    renderer: GraphRenderer,
    colors: ColorManager,
    config: Config | None = None,
) -> None:
    """Run in watch mode with continuous refresh.

    Args:
        state_file: StateFile instance
        graph_type: Type of graphs to render
        interval: Refresh interval in seconds
        renderer: GraphRenderer instance
        colors: ColorManager instance
        config: Config instance for motion settings
    """

    # Signal handler for clean exit
    def handle_signal(_signum: int, _frame: object) -> None:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()
        print(f"\n{colors.dim}Watch mode stopped.{colors.reset}")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Hide cursor and initial clear in one write
    sys.stdout.write(f"{HIDE_CURSOR}{CLEAR_SCREEN}{CURSOR_HOME}")
    sys.stdout.flush()

    cycle_counter = 0

    try:
        while True:
            # Update dimensions in case of terminal resize
            renderer.dimensions = GraphDimensions.detect()

            # Build all output into a buffer
            buf_lines: list[str] = []

            # Watch mode indicator
            current_time = time.strftime("%H:%M:%S")
            buf_lines.append(
                f"{colors.dim}[LIVE {current_time}] Refresh: {interval}s | Ctrl+C to exit{colors.reset}"
            )

            # Check if state file exists now (may have been created since start)
            file_path = state_file.find_latest_state_file()
            if not file_path or not file_path.exists():
                # Show waiting message for new session
                reduced_motion = config.reduced_motion if config else False
                text = get_waiting_text(cycle_counter, reduced_motion)
                buf_lines.append(
                    _format_waiting_message(
                        colors,
                        state_file.session_id,
                        text,
                    )
                )
            else:
                # Render graphs (returns buffered string in watch mode)
                result = render_once(
                    state_file,
                    graph_type,
                    renderer,
                    colors,
                    watch_mode=True,
                    config=config,
                    cycle_index=cycle_counter,
                )
                if isinstance(result, str):
                    buf_lines.append(result)

            # Atomic write: CURSOR_HOME + content + CLEAR_TO_END (clean up stale trailing lines)
            buffered_content = "\n".join(buf_lines)
            sys.stdout.write(f"{CURSOR_HOME}{buffered_content}\n{CLEAR_TO_END}")
            sys.stdout.flush()

            cycle_counter += 1
            time.sleep(interval)
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()


def _format_waiting_message(
    colors: ColorManager,
    session_id: str | None,
    message: str = "Waiting for session data...",
) -> str:
    """Format a waiting message as a string.

    Args:
        colors: ColorManager instance
        session_id: Session ID if specified
        message: Message to display

    Returns:
        Formatted waiting message string
    """
    lines = [""]
    if session_id:
        lines.append(
            f"{colors.bold}{colors.magenta}Context Stats{colors.reset} "
            f"{colors.dim}(Session: {session_id}){colors.reset}"
        )
    else:
        lines.append(f"{colors.bold}{colors.magenta}Context Stats{colors.reset}")
    lines.append("")
    lines.append(f"  {colors.cyan}⏳ {message}{colors.reset}")
    lines.append("")
    lines.append(
        f"  {colors.dim}The session has just started and no data has been recorded yet.{colors.reset}"
    )
    lines.append(
        f"  {colors.dim}Data will appear after the first Claude interaction.{colors.reset}"
    )
    lines.append("")
    return "\n".join(lines)


def show_waiting_message(
    colors: ColorManager,
    session_id: str | None,
    message: str = "Waiting for session data...",
) -> None:
    """Show a friendly waiting message for new sessions.

    Args:
        colors: ColorManager instance
        session_id: Session ID if specified
        message: Message to display
    """
    print(_format_waiting_message(colors, session_id, message))


def run_sessions(minutes: int, colors: ColorManager) -> None:
    """List recent sessions within the given time window.

    Args:
        minutes: Show sessions active within the last N minutes
        colors: ColorManager instance
    """
    state_file = StateFile(None)
    cutoff = time.time() - (minutes * 60)

    sessions: list[tuple[float, str, Path]] = []
    for file_path in state_file.STATE_DIR.glob("statusline.*.state"):
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            name = file_path.stem
            if name.startswith("statusline."):
                session_id = name.removeprefix("statusline.")
                if session_id:
                    sessions.append((mtime, session_id, file_path))

    # Sort by most recent first
    sessions.sort(key=lambda x: x[0], reverse=True)

    if not sessions:
        print(f"{colors.yellow}No sessions found in the last {minutes} minute(s).{colors.reset}")
        print(f"{colors.dim}Tip: Use --minutes N to widen the search window.{colors.reset}")
        return

    now = time.time()
    print(
        f"\n{colors.bold}{colors.magenta}Recent Sessions{colors.reset} "
        f"{colors.dim}(last {minutes} min){colors.reset}\n"
    )

    for mtime, session_id, _file_path in sessions:
        # Read last entry for metadata
        sf = StateFile(session_id)
        last_entry = sf.read_last_entry()

        # Format time ago
        ago = now - mtime
        if ago < 60:
            ago_str = f"{int(ago)}s ago"
        else:
            mins = int(ago // 60)
            secs = int(ago % 60)
            ago_str = f"{mins}m {secs}s ago" if secs else f"{mins}m ago"

        # Extract metadata
        project = ""
        model = ""
        tokens = ""
        if last_entry:
            if last_entry.workspace_project_dir:
                project = Path(last_entry.workspace_project_dir).name
            model = last_entry.model_id or ""
            total = last_entry.current_used_tokens
            if total >= 1_000_000:
                tokens = f"{total / 1_000_000:.1f}M tokens"
            elif total >= 1_000:
                tokens = f"{total / 1_000:.0f}K tokens"
            else:
                tokens = f"{total} tokens"

        # Display
        print(f"  {colors.cyan}{session_id}{colors.reset}")
        details = []
        if project:
            details.append(f"{colors.green}{project}{colors.reset}")
        if model:
            details.append(f"{colors.dim}{model}{colors.reset}")
        if tokens:
            details.append(tokens)
        details.append(f"{colors.dim}{ago_str}{colors.reset}")
        print(f"    {' · '.join(details)}")
        print()

    print(f"{colors.dim}Tip: context-stats {sessions[0][1]} graph{colors.reset}")


def _ensure_utf8_stdout() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows where cp1252 is the default."""
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if sys.stderr.encoding and sys.stderr.encoding.lower().replace("-", "") != "utf8":
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def main() -> None:
    """Main entry point for context-stats CLI."""
    _ensure_utf8_stdout()

    args = parse_args()

    if args.action == "explain":
        import json

        from claude_statusline.cli.explain import run_explain

        no_color = "--no-color" in sys.argv
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"Error: invalid JSON on stdin: {e}\n")
            sys.stderr.write("Usage: echo '{...}' | context-stats explain\n")
            sys.exit(1)
        run_explain(data, no_color=no_color)
        return

    if args.action == "export":
        from claude_statusline.cli.export import run_export

        # Build argv for export: inject session_id if resolved, then pass remaining flags
        export_argv: list[str] = []
        if args.session_id is not None:
            export_argv.append(args.session_id)
        export_argv.extend(args.remaining)
        run_export(export_argv)
        return

    if args.action == "cache-warm":
        from claude_statusline.cli.cache_warm import run_cache_warm

        session_id = args.session_id
        if session_id is None:
            # Resolve latest session for cache-warm (requires a real session_id)
            sf = StateFile(None)
            latest = sf.find_latest_state_file()
            if latest:
                session_id = latest.stem.removeprefix("statusline.")
            else:
                sys.stderr.write("Error: No session data found. Cannot start cache-warm.\n")
                sys.exit(1)

        color_enabled = "--no-color" not in sys.argv and sys.stdout.isatty()
        colors = ColorManager(enabled=color_enabled)
        run_cache_warm(session_id, args.remaining, colors)
        return

    if args.action == "sessions":
        color_enabled = "--no-color" not in sys.argv and sys.stdout.isatty()
        colors = ColorManager(enabled=color_enabled)
        if args.session_id is not None:
            sys.stderr.write(
                f"Error: 'sessions' does not accept a session_id (got '{args.session_id}')\n"
            )
            sys.exit(1)
        # Parse --minutes flag from remaining args
        minutes = 5
        remaining = args.remaining if hasattr(args, "remaining") else []
        i = 0
        while i < len(remaining):
            arg = remaining[i]
            if arg == "--minutes":
                if i + 1 >= len(remaining):
                    sys.stderr.write("Error: --minutes requires a value\n")
                    sys.exit(1)
                try:
                    minutes = int(remaining[i + 1])
                except ValueError:
                    sys.stderr.write(f"Error: Invalid value for --minutes: '{remaining[i + 1]}'\n")
                    sys.exit(1)
                if minutes <= 0:
                    sys.stderr.write(
                        f"Error: --minutes must be a positive integer (got {minutes})\n"
                    )
                    sys.exit(1)
                i += 2
            elif arg == "--no-color":
                i += 1
            elif arg.startswith("-"):
                sys.stderr.write(f"Error: Unknown flag for sessions: '{arg}'\n")
                sys.exit(1)
            else:
                sys.stderr.write(f"Error: Unexpected argument for sessions: '{arg}'\n")
                sys.exit(1)
        run_sessions(minutes, colors)
        return

    if args.action == "report":
        from claude_statusline.cli.report import run_report

        run_report(args.remaining)
        return

    # Default action: graph
    # Load config for token_detail setting
    config = Config.load()

    # Setup colors with any user overrides from config
    color_enabled = not args.no_color and sys.stdout.isatty()
    colors = ColorManager(enabled=color_enabled, overrides=config.color_overrides)

    # Setup state file
    state_file = StateFile(args.session_id)

    # Find state file
    file_path = state_file.find_latest_state_file()

    # Handle case where no state file exists yet
    if not file_path or not file_path.exists():
        if args.no_watch:
            # Single run mode - show friendly message and exit
            if args.session_id:
                show_waiting_message(colors, args.session_id)
            else:
                print(f"{colors.yellow}No session data found.{colors.reset}")
                print(f"{colors.dim}Run Claude Code to generate token usage data.{colors.reset}")
            sys.exit(0)
        else:
            # Watch mode - continue and wait for data
            pass

    # Setup renderer
    renderer = GraphRenderer(
        colors=colors,
        token_detail=config.token_detail,
    )

    # Run
    if args.no_watch:
        success = render_once(state_file, args.type, renderer, colors, config=config)
        if not success:
            sys.exit(1)
    else:
        run_watch_mode(state_file, args.type, args.watch, renderer, colors, config=config)


if __name__ == "__main__":
    main()
