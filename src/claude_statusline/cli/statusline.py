#!/usr/bin/env python3
"""CLI entry point for claude-statusline command.

Usage: Copy to ~/.claude/statusline.py and make executable, or install via pip.

Configuration:
Create/edit ~/.claude/statusline.conf and set:

  autocompact=true   (when autocompact is enabled in Claude Code - default)
  autocompact=false  (when you disable autocompact via /config in Claude Code)

  token_detail=true  (show exact token count like 64,000 - default)
  token_detail=false (show abbreviated tokens like 64.0k)

  show_delta=true    (show token delta since last refresh like [+2,500] - default)
  show_delta=false   (disable delta display - saves file I/O on every refresh)

  show_session=true  (show session_id in status line - default)
  show_session=false (hide session_id from status line)

When AC is enabled, 22.5% of context window is reserved for autocompact buffer.
"""

from __future__ import annotations

import json
import sys

from claude_statusline.core.colors import ColorManager
from claude_statusline.core.config import Config
from claude_statusline.core.git import get_git_info
from claude_statusline.core.state import StateEntry, StateFile
from claude_statusline.formatters.layout import fit_to_width, get_terminal_width
from claude_statusline.formatters.time import get_current_timestamp
from claude_statusline.formatters.tokens import calculate_context_usage, format_tokens


def main() -> None:
    """Main entry point for claude-statusline CLI."""
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("[Claude] ~")
        return

    # Extract data
    cwd = data.get("workspace", {}).get("current_dir", "~")
    project_dir = data.get("workspace", {}).get("project_dir", cwd)
    model = data.get("model", {}).get("display_name", "Claude")
    dir_name = cwd.rsplit("/", 1)[-1] if "/" in cwd else cwd or "~"

    # Read settings from config file
    config = Config.load()

    # Build color manager with any user overrides
    colors = ColorManager(enabled=True, overrides=config.color_overrides)

    # Git info (use per-property branch color if set, else fallback to magenta)
    branch_color = colors.branch_name
    # Build a color manager with branch_name mapped to magenta slot for git_info
    git_colors = ColorManager(enabled=True, overrides={**config.color_overrides, "magenta": branch_color})
    git_info = get_git_info(project_dir, color_manager=git_colors)

    # Extract session_id once for reuse
    session_id = data.get("session_id")

    # Context window calculation
    context_info = ""
    delta_info = ""
    mi_info = ""
    zone_info = ""
    session_info = ""

    total_size = data.get("context_window", {}).get("context_window_size", 0)
    current_usage = data.get("context_window", {}).get("current_usage")
    total_input_tokens = data.get("context_window", {}).get("total_input_tokens", 0)
    total_output_tokens = data.get("context_window", {}).get("total_output_tokens", 0)
    cost_usd = data.get("cost", {}).get("total_cost_usd", 0)
    lines_added = data.get("cost", {}).get("total_lines_added", 0)
    lines_removed = data.get("cost", {}).get("total_lines_removed", 0)
    model_id = data.get("model", {}).get("id", "")
    workspace_project_dir = data.get("workspace", {}).get("project_dir", "")

    if total_size > 0 and current_usage:
        # Get tokens from current_usage (includes cache)
        input_tokens = current_usage.get("input_tokens", 0)
        cache_creation = current_usage.get("cache_creation_input_tokens", 0)
        cache_read = current_usage.get("cache_read_input_tokens", 0)

        # Total used from current request
        used_tokens = input_tokens + cache_creation + cache_read

        # Calculate context usage
        free_tokens, free_pct, autocompact_buffer = calculate_context_usage(
            used_tokens,
            total_size,
            config.autocompact,
        )

        # Format tokens based on token_detail setting
        free_display = format_tokens(free_tokens, config.token_detail)

        # Color based on MI thresholds (consistent with MI display)
        from claude_statusline.graphs.intelligence import get_mi_color as _get_ctx_color, calculate_context_pressure, get_model_profile

        _utilization = used_tokens / total_size if total_size > 0 else 0.0
        _beta = get_model_profile(model_id)
        _mi = calculate_context_pressure(_utilization, _beta)
        ctx_color_name = _get_ctx_color(_mi, _utilization)
        ctx_color = getattr(colors, ctx_color_name)

        # Use per-property context_length color if configured, else MI-based color
        prop_ctx_color = config.color_overrides.get("context_length")
        effective_ctx_color = prop_ctx_color if prop_ctx_color else ctx_color

        context_info = f" | {effective_ctx_color}{free_display} ({free_pct:.1f}%){colors.reset}"

        # Always show zone indicator
        from claude_statusline.graphs.intelligence import get_context_zone

        zone_result = get_context_zone(used_tokens, total_size)
        # Use per-property zone color if configured, else dynamic zone color
        prop_zone_color = config.color_overrides.get("zone")
        if prop_zone_color:
            zone_color = prop_zone_color
        else:
            zone_color_map = {
                "green": colors.green,
                "yellow": colors.yellow,
                "orange": "\033[38;2;255;165;0m" if colors.enabled else "",
                "dark_red": "\033[38;2;139;0;0m" if colors.enabled else "",
                "gray": "\033[0;90m" if colors.enabled else "",
            }
            zone_color = zone_color_map.get(zone_result.color, colors.reset)
        zone_info = f" | {zone_color}{zone_result.zone}{colors.reset}"

        # State file management for delta display and history recording
        if config.show_delta or config.show_mi:
            state_file = StateFile(session_id)
            prev_entry = state_file.read_last_entry()
            has_prev = prev_entry is not None
            prev_tokens = prev_entry.current_used_tokens if prev_entry else 0

            # Build current entry
            cur_input_tokens = current_usage.get("input_tokens", 0)
            cur_output_tokens = current_usage.get("output_tokens", 0)

            entry = StateEntry(
                timestamp=get_current_timestamp(),
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                current_input_tokens=cur_input_tokens,
                current_output_tokens=cur_output_tokens,
                cache_creation=cache_creation,
                cache_read=cache_read,
                cost_usd=cost_usd,
                lines_added=lines_added,
                lines_removed=lines_removed,
                session_id=session_id or "",
                model_id=model_id,
                workspace_project_dir=workspace_project_dir,
                context_window_size=total_size,
            )

            # Calculate and display token delta if enabled
            if config.show_delta:
                delta = used_tokens - prev_tokens
                if has_prev and delta > 0:
                    delta_display = format_tokens(delta, config.token_detail)
                    delta_info = f" | {colors.separator}+{delta_display}{colors.reset}"

            # Calculate MI score — pure function of utilization, no prev entry needed
            if config.show_mi:
                from claude_statusline.graphs.intelligence import (
                    calculate_intelligence,
                    format_mi_score,
                    get_mi_color,
                )

                mi_score = calculate_intelligence(
                    entry, total_size, model_id, config.mi_curve_beta
                )
                mi_color_name = get_mi_color(mi_score.mi, mi_score.utilization)
                mi_color = getattr(colors, mi_color_name)
                # Use per-property mi_score color if configured, else MI-based color
                prop_mi_color = config.color_overrides.get("mi_score")
                effective_mi_color = prop_mi_color if prop_mi_color else mi_color
                mi_info = f" | {effective_mi_color}MI:{format_mi_score(mi_score.mi)}{colors.reset}"

            # Only append if context usage changed (avoid duplicates)
            if not has_prev or used_tokens != prev_tokens:
                state_file.append_entry(entry)

    # Display session_id if enabled
    if config.show_session and session_id:
        session_info = f" | {colors.separator}{session_id}{colors.reset}"

    # Output: [Model] directory | branch [changes] | XXk free (XX%) [+delta] [AC] [session_id]
    base = f"{colors.separator}{model}{colors.reset} | {colors.project_name}{dir_name}{colors.reset}"
    max_width = get_terminal_width()
    parts = [base, git_info, context_info, zone_info, mi_info, delta_info, session_info]
    print(fit_to_width(parts, max_width))


if __name__ == "__main__":
    main()
