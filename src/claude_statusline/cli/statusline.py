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

Structure (Task 5.6, F-CLEAN-008): ``main()`` is a transport-only entry
point — parse stdin, render, fall back on unexpected errors. ``_render``
orchestrates over an extracted :class:`StatusPayload`, per-concern segment
builders, and a stateful metrics helper; ANSI/separator literals live in
``core/colors.py``.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Render-glue helpers are single-sourced in _shared (Task 5.2, F-DEAD-001);
# the standalone script loads the same bodies from claude_statusline._shared /
# its vendored copy.
from claude_statusline._shared import (
    _TPS_TAIL_BUFFER as _TPS_TAIL_BUFFER,
)
from claude_statusline._shared import (
    _ensure_utf8_stdout,
    _extract,
    _format_thinking_info,
    _resolve_project_dir,
    _tps_tail_size,
)
from claude_statusline.core.colors import (
    INLINE_SEPARATOR,
    SEGMENT_SEPARATOR,
    ColorManager,
)
from claude_statusline.core.config import Config
from claude_statusline.core.git import _get_pr_number, get_git_info
from claude_statusline.core.state import StateEntry, StateFile, _validate_session_id
from claude_statusline.formatters.layout import fit_to_width, get_terminal_width
from claude_statusline.formatters.time import get_current_timestamp
from claude_statusline.formatters.tokens import calculate_context_usage, format_tokens
from claude_statusline.graphs.intelligence import (
    ZoneThresholds,
    calculate_intelligence,
    format_mi_score,
    get_context_zone,
    get_mi_color,
)
from claude_statusline.graphs.statistics import compute_tps, format_tps


def _validate_session_id_or_none(session_id: Any) -> Any:
    """Return ``session_id`` when safe, else None after a stderr warning.

    Path-traversal defense (F-BUG-002): a session_id carrying ``/``, ``\\``,
    ``..`` or null bytes must never reach state-file path construction. The
    package degrades to the default state file instead of crashing.
    """
    if session_id is None:
        return None
    try:
        _validate_session_id(session_id)
    except ValueError as e:
        sys.stderr.write(f"[statusline] warning: {e}\n")
        return None
    return session_id


@dataclass(frozen=True)
class StatusPayload:
    """Everything one status-line render needs from the stdin JSON blob."""

    cwd: str
    project_dir: str
    dir_name: str
    model: str
    model_id: str
    thinking_budget: int | None
    effort_level: str | None
    session_id: str | None
    total_size: int
    current_usage: Any
    total_input_tokens: int
    total_output_tokens: int
    cost_usd: float
    lines_added: int
    lines_removed: int
    api_duration_ms: int
    workspace_project_dir: str


def extract_payload(data: dict) -> StatusPayload:
    """Extract every stdin field the render needs (Task 5.6, F-CLEAN-008).

    Every lookup treats explicit JSON null like an absent key. The session_id
    is validated here so no downstream consumer can see an unsafe value.
    """
    workspace_data = _extract(data, "workspace", {})
    cwd = _extract(workspace_data, "current_dir", "~")
    project_dir = _extract(workspace_data, "project_dir", cwd)
    model_data = _extract(data, "model", {})
    model = _extract(model_data, "display_name", "Claude")
    # Extract thinking budget if present (forward-compatible: Claude Code may send this)
    thinking_budget = model_data.get("thinking_budget") or (
        model_data.get("thinking", {}).get("budget")
        if isinstance(model_data.get("thinking"), dict)
        else None
    )
    # Reasoning effort level (low/medium/high/xhigh/max) if Claude Code sends it.
    # `effort` is conditionally present and may arrive as explicit null or an
    # unexpected shape; guard with isinstance so a non-dict value cannot crash
    # the whole statusline (mirrors the `thinking` extraction above).
    effort_data = data.get("effort")
    effort_level = effort_data.get("level") if isinstance(effort_data, dict) else None

    context_data = _extract(data, "context_window", {})
    cost_data = _extract(data, "cost", {})

    return StatusPayload(
        cwd=cwd,
        project_dir=project_dir,
        dir_name=os.path.basename(cwd) or "~",
        model=model,
        model_id=_extract(model_data, "id", ""),
        thinking_budget=thinking_budget,
        effort_level=effort_level,
        session_id=_validate_session_id_or_none(_extract(data, "session_id")),
        total_size=_extract(context_data, "context_window_size", 0),
        current_usage=_extract(context_data, "current_usage"),
        total_input_tokens=_extract(context_data, "total_input_tokens", 0),
        total_output_tokens=_extract(context_data, "total_output_tokens", 0),
        cost_usd=_extract(cost_data, "total_cost_usd", 0) or 0,
        lines_added=_extract(cost_data, "total_lines_added", 0),
        lines_removed=_extract(cost_data, "total_lines_removed", 0),
        api_duration_ms=_extract(cost_data, "total_api_duration_ms", 0),
        workspace_project_dir=_extract(workspace_data, "project_dir", ""),
    )


def _build_git_segment(payload: StatusPayload, config: Config, colors: ColorManager) -> str:
    """Git branch info, gated on the resolved project dir (F-SEC-002)."""
    safe_project_dir = _resolve_project_dir(payload.project_dir)
    if not safe_project_dir:
        return ""
    # Git info uses per-property branch color if set, else fallback to magenta;
    # build a color manager with branch_name mapped to magenta slot for git_info
    # while keeping every other configured override.
    git_colors = ColorManager(
        enabled=True,
        overrides={**config.color_overrides, "magenta": colors.branch_name},
    )
    return get_git_info(safe_project_dir, color_manager=git_colors)


def _build_pr_segment(payload: StatusPayload, config: Config, colors: ColorManager) -> str:
    """PR number segment from the gh CLI cache, when enabled."""
    safe_project_dir = _resolve_project_dir(payload.project_dir)
    if not (config.show_pr and safe_project_dir):
        return ""
    pr_num = _get_pr_number(Path(safe_project_dir))
    if not pr_num:
        return ""
    return f"{SEGMENT_SEPARATOR}{colors.separator}{pr_num}{colors.reset}"


@dataclass(frozen=True)
class _UsageSegments:
    """Rendered context-window segments plus the stateful metric segments."""

    context: str = ""
    zone: str = ""
    pacman: str = ""
    mi: str = ""
    tps: str = ""
    delta: str = ""


def _build_usage_segments(
    payload: StatusPayload, config: Config, colors: ColorManager
) -> _UsageSegments:
    """Build the tokens·zone·pacman group and delta/MI/tok-s segments.

    Also performs the state-file read/append cycle the metrics depend on;
    skipped entirely when none of those metrics are enabled.
    """
    if not (payload.total_size > 0 and payload.current_usage):
        return _UsageSegments()

    # Get tokens from current_usage (includes cache)
    input_tokens = payload.current_usage.get("input_tokens", 0)
    cache_creation = payload.current_usage.get("cache_creation_input_tokens", 0)
    cache_read = payload.current_usage.get("cache_read_input_tokens", 0)

    # Total used from current request
    used_tokens = input_tokens + cache_creation + cache_read

    # Calculate context usage
    free_tokens, free_pct, _autocompact_buffer = calculate_context_usage(
        used_tokens,
        payload.total_size,
        config.autocompact,
    )

    # Format tokens based on token_detail setting
    free_display = format_tokens(free_tokens, config.token_detail)

    # Zone indicator — determines color for both context info and zone label
    zone_result = get_context_zone(
        used_tokens, payload.total_size, thresholds=ZoneThresholds.from_config(config)
    )

    # Traffic-light color via core/colors.py (F-CLEAN-008: no ANSI literals here)
    zone_color = colors.zone_color(zone_result.color)

    # Context info uses zone color (traffic-light), with per-property override
    prop_ctx_color = config.color_overrides.get("context_length")
    effective_ctx_color = prop_ctx_color if prop_ctx_color else zone_color
    context_info = (
        f"{SEGMENT_SEPARATOR}{effective_ctx_color}{free_display} ({free_pct:.1f}%){colors.reset}"
    )

    # Zone label uses same color, with per-property override
    prop_zone_color = config.color_overrides.get("zone")
    effective_zone_color = prop_zone_color if prop_zone_color else zone_color
    zone_info = f"{INLINE_SEPARATOR}{effective_zone_color}{zone_result.zone}{colors.reset}"

    # Pacman-style icon reflecting the same zone — on by default.
    pacman_info = ""
    if config.show_pacman:
        from claude_statusline.graphs.intelligence import get_pacman_icon

        pacman_glyph = get_pacman_icon(zone_result.zone)
        if pacman_glyph:
            pacman_info = f"{INLINE_SEPARATOR}{effective_zone_color}{pacman_glyph}{colors.reset}"

    metrics = _build_metric_segments(
        payload, config, colors, used_tokens, cache_creation, cache_read
    )
    return _UsageSegments(context_info, zone_info, pacman_info, metrics[0], metrics[1], metrics[2])


def _build_metric_segments(
    payload: StatusPayload,
    config: Config,
    colors: ColorManager,
    used_tokens: int,
    cache_creation: int,
    cache_read: int,
) -> tuple[str, str, str]:
    """Delta / MI / tok-s segments backed by state history.

    tok/s also needs the previous row (for the API-time delta) and must
    persist the current api_duration for the next refresh, so it widens this
    gate alongside show_delta / show_mi. Returns (mi_info, tps_info,
    delta_info).
    """
    if not (config.show_delta or config.show_mi or config.show_tps):
        return ("", "", "")

    state_file = StateFile(payload.session_id)
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

    entry = StateEntry(
        timestamp=get_current_timestamp(),
        total_input_tokens=payload.total_input_tokens,
        total_output_tokens=payload.total_output_tokens,
        current_input_tokens=payload.current_usage.get("input_tokens", 0),
        current_output_tokens=payload.current_usage.get("output_tokens", 0),
        cache_creation=cache_creation,
        cache_read=cache_read,
        cost_usd=payload.cost_usd,
        lines_added=payload.lines_added,
        lines_removed=payload.lines_removed,
        session_id=payload.session_id or "",
        model_id=payload.model_id,
        workspace_project_dir=payload.workspace_project_dir,
        context_window_size=payload.total_size,
        api_duration_ms=payload.api_duration_ms,
    )

    # Calculate and display token delta if enabled
    delta_info = ""
    if config.show_delta:
        delta = used_tokens - prev_tokens
        if has_prev and delta > 0:
            delta_display = format_tokens(delta, config.token_detail)
            delta_info = f"{SEGMENT_SEPARATOR}{colors.delta}+{delta_display}{colors.reset}"

    # Calculate MI score — pure function of utilization, no prev entry needed
    mi_info = ""
    if config.show_mi:
        mi_score = calculate_intelligence(
            entry, payload.total_size, payload.model_id, config.mi_curve_beta
        )
        mi_color_name = get_mi_color(mi_score.mi, mi_score.utilization)
        mi_color = getattr(colors, mi_color_name)
        # Use per-property mi_score color if configured, else MI-based color
        prop_mi_color = config.color_overrides.get("mi_score")
        effective_mi_color = prop_mi_color if prop_mi_color else mi_color
        mi_info = f"{SEGMENT_SEPARATOR}{effective_mi_color}MI:{format_mi_score(mi_score.mi)}{colors.reset}"

    # Calculate model throughput (tok/s) as a rolling, token-weighted
    # average over the last N turns reconstructed from state history
    # plus the live reading.
    tps_info = ""
    if config.show_tps:
        samples = [(e.current_output_tokens, e.api_duration_ms) for e in history]
        samples.append((payload.current_usage.get("output_tokens", 0), payload.api_duration_ms))
        tps = compute_tps(samples, window=config.tps_window)
        if tps is not None:
            tps_display = format_tps(tps, config.tps_precision, config.tps_unit)
            tps_info = f"{SEGMENT_SEPARATOR}{colors.tps}{tps_display}{colors.reset}"

    # Only append if context usage changed (avoid duplicates)
    if not has_prev or used_tokens != prev_tokens:
        state_file.append_entry(entry)

    return (mi_info, tps_info, delta_info)


def main() -> None:
    """Main entry point for claude-statusline CLI."""
    _ensure_utf8_stdout()

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("[Claude] ~")
        return

    # Render catch-all (F-BUG-004): any unexpected exception degrades to a
    # minimal status line on stdout with diagnostics on stderr only — never a
    # raw traceback as the status line.
    try:
        _render(data)
    except Exception:  # noqa: BLE001 - deliberate catch-all render boundary
        sys.stderr.write("[statusline] warning: rendering failed; fallback line emitted\n")
        sys.stderr.write(traceback.format_exc())
        print("[Claude] ~")


def _render(data: dict) -> None:
    """Render the status line for an already-parsed stdin payload."""
    payload = extract_payload(data)

    # Read settings from config file
    config = Config.load()

    # Build color manager with any user overrides
    colors = ColorManager(enabled=True, overrides=config.color_overrides)

    git_info = _build_git_segment(payload, config, colors)
    pr_info = _build_pr_segment(payload, config, colors)
    usage = _build_usage_segments(payload, config, colors)

    # Session cost (cumulative USD) if enabled — shown even at $0.00 so the
    # segment doesn't flicker in and out across the first few turns.
    cost_info = ""
    if config.show_cost:
        cost_info = f"{SEGMENT_SEPARATOR}{colors.cost}${payload.cost_usd:.2f}{colors.reset}"

    # Display session_id if enabled
    session_info = ""
    if config.show_session and payload.session_id:
        session_info = f"{SEGMENT_SEPARATOR}{colors.session}{payload.session_id}{colors.reset}"

    # Output: directory | branch [changes] | XXk free (XX%)·zone·pacman | MI | +delta | $cost | [Model] [session_id]
    # Model name is lowest priority — wraps to a new line first when narrow
    base = f"{colors.project_name}{payload.dir_name}{colors.reset}"
    thinking_text = _format_thinking_info(payload.thinking_budget)
    # Build the model suffix from any present indicators (thinking budget,
    # reasoning effort). Effort hides gracefully when absent/null/disabled.
    model_suffix = ""
    if thinking_text:
        model_suffix += f"{INLINE_SEPARATOR}{thinking_text}"
    if config.show_effort and payload.effort_level:
        model_suffix += f"{INLINE_SEPARATOR}{payload.effort_level}"
    model_info = f"{SEGMENT_SEPARATOR}{colors.model}{payload.model}{model_suffix}{colors.reset}"
    max_width = get_terminal_width()
    parts = [
        base,
        git_info,
        pr_info,
        # Context group: tokens·zone·pacman. Joined with "·" (no spaces) and
        # kept as ONE atomic part so the group never splits across lines on a
        # narrow terminal — fit_to_width() only strips a leading " | ", so a
        # "·"-prefixed part starting a wrapped line would show a stray "·".
        usage.context + usage.zone + usage.pacman,
        usage.mi,
        usage.tps,
        usage.delta,
        cost_info,
        model_info,
        session_info,
    ]
    print(fit_to_width(parts, max_width))


if __name__ == "__main__":
    main()
