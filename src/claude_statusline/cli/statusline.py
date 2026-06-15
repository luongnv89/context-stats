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
from pathlib import Path

from claude_statusline.core.colors import ColorManager
from claude_statusline.core.config import Config
from claude_statusline.core.git import _get_pr_number, get_git_info
from claude_statusline.core.state import StateEntry, StateFile
from claude_statusline.formatters.layout import fit_to_width, get_terminal_width
from claude_statusline.formatters.time import get_current_timestamp
from claude_statusline.formatters.tokens import calculate_context_usage, format_tokens

# Extra rows read beyond ``tps_window`` when tail-reading state history for
# tok/s. compute_tps needs the last ``tps_window`` valid *turns* (=
# ``tps_window + 1`` valid rows); this headroom absorbs the sparse, isolated
# dropped rows real histories contain (non-positive API-time delta, zero
# output) plus any legacy/blank rows, so the rendered value matches a
# full-history read. Kept small so each refresh still parses only a bounded
# tail. (A pathological run of >~``tps_window + 7`` consecutive dropped rows
# at the tail boundary cannot occur once tok/s is enabled: every appended row
# carries the api_duration field, so legacy rows can only be a leading prefix.)
_TPS_TAIL_BUFFER = 8


def _tps_tail_size(tps_window: int) -> int:
    """Number of trailing state rows to read for the tok/s rolling average.

    ``tps_window`` valid turns need ``tps_window + 1`` valid rows; doubling the
    window plus a fixed buffer leaves ample room for interleaved dropped rows
    while staying bounded (independent of total file size).
    """
    return max(1, tps_window) * 2 + _TPS_TAIL_BUFFER


def _format_thinking_info(budget) -> str:
    """Format thinking budget for display next to model name.

    Returns an empty string when budget is None or zero.
    Small budgets (< 1000) are shown exactly.
    Medium budgets (1000-9999) are shown as "Nk" only when rounding is reasonable (>= 5k).
    Large budgets (>= 1M) are shown as "NM" tokens thinking.
    """
    if budget is None or budget == 0:
        return ""
    try:
        tokens = int(budget)
    except (ValueError, TypeError):
        return ""
    if tokens <= 0:
        return ""
    if tokens >= 1_000_000:
        return f"{tokens // 1_000_000}M tokens thinking"
    if tokens >= 10_000:
        k = round(tokens / 1_000)
        return f"{k}k tokens thinking"
    if tokens >= 5_000:
        return f"{tokens // 1_000}k tokens thinking"
    return f"{tokens} tokens thinking"


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
    # Extract thinking budget if present (forward-compatible: Claude Code may send this)
    model_data = data.get("model", {})
    thinking_budget = model_data.get("thinking_budget") or (
        model_data.get("thinking", {}).get("budget")
        if isinstance(model_data.get("thinking"), dict)
        else None
    )
    # Reasoning effort level (low/medium/high/xhigh/max) if Claude Code sends it.
    # `effort` is conditionally present and may arrive as explicit null, so guard
    # with `or {}` (a {} default does not protect against an explicit null value).
    effort_level = (data.get("effort") or {}).get("level")
    dir_name = cwd.rsplit("/", 1)[-1] if "/" in cwd else cwd or "~"

    # Read settings from config file
    config = Config.load()

    # Build color manager with any user overrides
    colors = ColorManager(enabled=True, overrides=config.color_overrides)

    # Git info (use per-property branch color if set, else fallback to magenta)
    branch_color = colors.branch_name
    # Build a color manager with branch_name mapped to magenta slot for git_info
    git_colors = ColorManager(
        enabled=True, overrides={**config.color_overrides, "magenta": branch_color}
    )
    git_info = get_git_info(project_dir, color_manager=git_colors)

    # Extract session_id once for reuse
    session_id = data.get("session_id")

    # Context window calculation
    context_info = ""
    delta_info = ""
    mi_info = ""
    tps_info = ""
    cost_info = ""
    zone_info = ""
    session_info = ""
    pr_info = ""

    # PR number lookup (after other initialisations so we have the config)
    if config.show_pr:
        pr_num = _get_pr_number(Path(project_dir))
        if pr_num:
            pr_info = f" | {colors.separator}{pr_num}{colors.reset}"

    total_size = data.get("context_window", {}).get("context_window_size", 0)
    current_usage = data.get("context_window", {}).get("current_usage")
    total_input_tokens = data.get("context_window", {}).get("total_input_tokens", 0)
    total_output_tokens = data.get("context_window", {}).get("total_output_tokens", 0)
    cost_usd = data.get("cost", {}).get("total_cost_usd", 0) or 0
    lines_added = data.get("cost", {}).get("total_lines_added", 0)
    lines_removed = data.get("cost", {}).get("total_lines_removed", 0)
    api_duration_ms = data.get("cost", {}).get("total_api_duration_ms", 0)
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

        # Zone indicator — determines color for both context info and zone label
        from claude_statusline.graphs.intelligence import get_context_zone

        zone_result = get_context_zone(
            used_tokens,
            total_size,
            zone_1m_plan_max=config.zone_1m_plan_max,
            zone_1m_code_max=config.zone_1m_code_max,
            zone_1m_dump_max=config.zone_1m_dump_max,
            zone_1m_xdump_max=config.zone_1m_xdump_max,
            zone_std_dump_ratio=config.zone_std_dump_ratio,
            zone_std_warn_buffer=config.zone_std_warn_buffer,
            zone_std_hard_limit=config.zone_std_hard_limit,
            zone_std_dead_ratio=config.zone_std_dead_ratio,
            large_model_threshold=config.large_model_threshold,
        )

        # Traffic-light color map: green/yellow/orange/red/gray
        zone_color_map = {
            "green": colors.green,
            "yellow": colors.yellow,
            "orange": "\033[38;2;255;165;0m" if colors.enabled else "",
            "dark_red": "\033[38;2;139;0;0m" if colors.enabled else "",
            "gray": "\033[0;90m" if colors.enabled else "",
        }
        zone_color = zone_color_map.get(zone_result.color, colors.reset)

        # Context info uses zone color (traffic-light), with per-property override
        prop_ctx_color = config.color_overrides.get("context_length")
        effective_ctx_color = prop_ctx_color if prop_ctx_color else zone_color

        context_info = f" | {effective_ctx_color}{free_display} ({free_pct:.1f}%){colors.reset}"

        # Zone label uses same color, with per-property override
        prop_zone_color = config.color_overrides.get("zone")
        effective_zone_color = prop_zone_color if prop_zone_color else zone_color
        zone_info = f" | {effective_zone_color}{zone_result.zone}{colors.reset}"

        # State file management for delta/MI/throughput display and history.
        # tok/s also needs the previous row (for the API-time delta) and must
        # persist the current api_duration for the next refresh, so it widens
        # this gate alongside show_delta / show_mi.
        if config.show_delta or config.show_mi or config.show_tps:
            state_file = StateFile(session_id)
            # tok/s needs a rolling window of recent rows; delta/MI only need
            # the last row. For tok/s, read a bounded *tail* rather than the
            # whole file: compute_tps only needs the last ``tps_window`` valid
            # turns (i.e. ``tps_window + 1`` valid rows). We read a slightly
            # larger tail so the sparse, isolated dropped/legacy/blank rows seen
            # in real histories don't starve the window, while parsing at most a
            # bounded number of rows per refresh (independent of file size).
            # Legacy rows (no api_duration field) only ever form a historical
            # prefix, so on any file the writer produces the rendered tok/s is
            # identical to a full-history read.
            if config.show_tps:
                tail_n = _tps_tail_size(config.tps_window)
                history = state_file.read_tail(tail_n)
                prev_entry = history[-1] if history else None
            else:
                history = []
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
                api_duration_ms=api_duration_ms,
            )

            # Calculate and display token delta if enabled
            if config.show_delta:
                delta = used_tokens - prev_tokens
                if has_prev and delta > 0:
                    delta_display = format_tokens(delta, config.token_detail)
                    delta_info = f" | {colors.delta}+{delta_display}{colors.reset}"

            # Calculate MI score — pure function of utilization, no prev entry needed
            if config.show_mi:
                from claude_statusline.graphs.intelligence import (
                    calculate_intelligence,
                    format_mi_score,
                    get_mi_color,
                )

                mi_score = calculate_intelligence(entry, total_size, model_id, config.mi_curve_beta)
                mi_color_name = get_mi_color(mi_score.mi, mi_score.utilization)
                mi_color = getattr(colors, mi_color_name)
                # Use per-property mi_score color if configured, else MI-based color
                prop_mi_color = config.color_overrides.get("mi_score")
                effective_mi_color = prop_mi_color if prop_mi_color else mi_color
                mi_info = f" | {effective_mi_color}MI:{format_mi_score(mi_score.mi)}{colors.reset}"

            # Calculate model throughput (tok/s) as a rolling, token-weighted
            # average over the last N turns reconstructed from state history
            # plus the live reading.
            if config.show_tps:
                from claude_statusline.graphs.statistics import compute_tps, format_tps

                samples = [(e.current_output_tokens, e.api_duration_ms) for e in history]
                samples.append((cur_output_tokens, api_duration_ms))
                tps = compute_tps(samples, window=config.tps_window)
                if tps is not None:
                    tps_display = format_tps(tps, config.tps_precision, config.tps_unit)
                    tps_info = f" | {colors.tps}{tps_display}{colors.reset}"

            # Only append if context usage changed (avoid duplicates)
            if not has_prev or used_tokens != prev_tokens:
                state_file.append_entry(entry)

    # Session cost (cumulative USD) if enabled — shown even at $0.00 so the
    # segment doesn't flicker in and out across the first few turns.
    if config.show_cost:
        cost_info = f" | {colors.cost}${cost_usd:.2f}{colors.reset}"

    # Display session_id if enabled
    if config.show_session and session_id:
        session_info = f" | {colors.session}{session_id}{colors.reset}"

    # Output: directory | branch [changes] | XXk free (XX%) | zone | MI | +delta | $cost | [Model] [session_id]
    # Model name is lowest priority — truncated first when terminal is narrow
    base = f"{colors.project_name}{dir_name}{colors.reset}"
    thinking_text = _format_thinking_info(thinking_budget)
    # Build the model suffix from any present indicators (thinking budget,
    # reasoning effort). Effort hides gracefully when absent/null/disabled.
    model_suffix = ""
    if thinking_text:
        model_suffix += f" · {thinking_text}"
    if config.show_effort and effort_level:
        model_suffix += f" · {effort_level}"
    model_info = f" | {colors.model}{model}{model_suffix}{colors.reset}"
    max_width = get_terminal_width()
    parts = [
        base,
        git_info,
        pr_info,
        context_info,
        zone_info,
        mi_info,
        tps_info,
        delta_info,
        cost_info,
        model_info,
        session_info,
    ]
    print(fit_to_width(parts, max_width))


if __name__ == "__main__":
    main()
