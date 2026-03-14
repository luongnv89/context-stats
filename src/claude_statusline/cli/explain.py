"""Diagnostic command that dumps the raw JSON context from Claude Code.

Usage:
    echo '{"model":...}' | context-stats explain
    echo '{"model":...}' | context-stats explain --no-color

Reads the same JSON that Claude Code pipes to the statusline script,
pretty-prints every field with labels, and shows how cc-context-stats
interprets them. Useful for debugging blank or missing modules.
"""

from __future__ import annotations

import json
import sys

from claude_statusline.core.colors import ColorManager
from claude_statusline.core.config import Config
from claude_statusline.formatters.tokens import format_tokens


def _pct_color(colors: ColorManager, pct: float) -> str:
    """Return ANSI color based on free-space percentage."""
    if pct > 50:
        return colors.green
    if pct > 25:
        return colors.yellow
    return colors.red


def _fv(colors: ColorManager, value: object) -> str:
    """Format a value for display, handling None gracefully."""
    if value is None:
        return f"{colors.dim}(absent){colors.reset}"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _render_model(data: dict, colors: ColorManager) -> None:
    model = data.get("model", {})
    print(f"{colors.bold}Model{colors.reset}")
    print(f"  display_name:  {_fv(colors, model.get('display_name'))}")
    print(f"  id:            {_fv(colors, model.get('id'))}")
    print(f"  api_name:      {_fv(colors, model.get('api_name'))}")
    print()


def _render_workspace(data: dict, colors: ColorManager) -> None:
    workspace = data.get("workspace", {})
    print(f"{colors.bold}Workspace{colors.reset}")
    print(f"  current_dir:   {_fv(colors, workspace.get('current_dir'))}")
    print(f"  project_dir:   {_fv(colors, workspace.get('project_dir'))}")
    print()


def _render_context_window(data: dict, colors: ColorManager, config: Config) -> None:
    cw = data.get("context_window", {})
    print(f"{colors.bold}Context Window{colors.reset}")
    total_size = cw.get("context_window_size", 0)
    print(
        f"  window_size:   "
        f"{format_tokens(total_size, config.token_detail) if total_size else _fv(colors, None)}"
    )

    total_in = cw.get("total_input_tokens")
    total_out = cw.get("total_output_tokens")
    print(
        f"  total_input:   "
        f"{format_tokens(total_in, config.token_detail) if total_in else _fv(colors, total_in)}"
    )
    print(
        f"  total_output:  "
        f"{format_tokens(total_out, config.token_detail) if total_out else _fv(colors, total_out)}"
    )

    used_pct = cw.get("used_percentage")
    remaining_pct = cw.get("remaining_percentage")
    print(f"  used_pct:      {_fv(colors, used_pct)}")
    print(f"  remaining_pct: {_fv(colors, remaining_pct)}")

    cu = cw.get("current_usage")
    if cu:
        _render_current_usage(cu, total_size, colors, config)
    else:
        print(f"  current_usage: {colors.dim}(absent — no API call yet this session){colors.reset}")
    print()


def _render_current_usage(cu: dict, total_size: int, colors: ColorManager, config: Config) -> None:
    input_tok = cu.get("input_tokens", 0)
    output_tok = cu.get("output_tokens", 0)
    cache_create = cu.get("cache_creation_input_tokens", 0)
    cache_read = cu.get("cache_read_input_tokens", 0)
    used_tokens = input_tok + cache_create + cache_read

    print(f"\n  {colors.bold}Current Usage{colors.reset}")
    print(f"    input_tokens:            {format_tokens(input_tok, config.token_detail)}")
    print(f"    output_tokens:           {format_tokens(output_tok, config.token_detail)}")
    print(f"    cache_creation_tokens:   {format_tokens(cache_create, config.token_detail)}")
    print(f"    cache_read_tokens:       {format_tokens(cache_read, config.token_detail)}")

    print(f"\n  {colors.bold}Derived Values{colors.reset}")
    print(
        f"    context_used (in+cache): "
        f"{colors.cyan}{format_tokens(used_tokens, config.token_detail)}{colors.reset}"
    )

    if total_size > 0:
        free = total_size - used_tokens
        free_pct = (free * 100.0) / total_size
        color = _pct_color(colors, free_pct)
        print(
            f"    free_tokens:             "
            f"{color}{format_tokens(max(0, free), config.token_detail)} ({free_pct:.1f}%){colors.reset}"
        )

        if config.autocompact:
            ac_buffer = int(total_size * 0.225)
            effective_free = max(0, free - ac_buffer)
            eff_pct = (effective_free * 100.0) / total_size
            eff_color = _pct_color(colors, eff_pct)
            print(
                f"    autocompact_buffer:      "
                f"{colors.dim}{format_tokens(ac_buffer, config.token_detail)}{colors.reset}"
            )
            print(
                f"    effective_free (w/ AC):   "
                f"{eff_color}{format_tokens(effective_free, config.token_detail)}"
                f" ({eff_pct:.1f}%){colors.reset}"
            )
        else:
            print(f"    autocompact:             {colors.dim}disabled{colors.reset}")


def _render_cost(data: dict, colors: ColorManager) -> None:
    cost = data.get("cost", {})
    if not cost:
        return
    print(f"{colors.bold}Cost{colors.reset}")
    cost_usd = cost.get("total_cost_usd")
    print(
        f"  total_cost_usd:    {f'${cost_usd:.4f}' if cost_usd is not None else _fv(colors, None)}"
    )
    print(f"  total_duration_ms: {_fv(colors, cost.get('total_duration_ms'))}")
    print(f"  lines_added:       {_fv(colors, cost.get('total_lines_added'))}")
    print(f"  lines_removed:     {_fv(colors, cost.get('total_lines_removed'))}")
    print()


def _render_session(data: dict, colors: ColorManager) -> None:
    print(f"{colors.bold}Session{colors.reset}")
    print(f"  session_id:        {_fv(colors, data.get('session_id'))}")
    print(f"  version:           {_fv(colors, data.get('version'))}")
    print(f"  transcript_path:   {_fv(colors, data.get('transcript_path'))}")
    print(f"  exceeds_200k:      {_fv(colors, data.get('exceeds_200k_tokens'))}")
    print()


def _render_extensions(data: dict, colors: ColorManager) -> None:
    vim = data.get("vim")
    agent = data.get("agent")
    output_style = data.get("output_style")
    if vim is None and agent is None and output_style is None:
        return
    print(f"{colors.bold}Extensions{colors.reset}")
    if vim is not None:
        vim_mode = vim.get("mode") if isinstance(vim, dict) else vim
        print(f"  vim_mode:          {_fv(colors, vim_mode)}")
    if agent is not None:
        agent_name = agent.get("name") if isinstance(agent, dict) else agent
        print(f"  agent:             {_fv(colors, agent_name)}")
    if output_style is not None:
        style_name = output_style.get("name") if isinstance(output_style, dict) else output_style
        print(f"  output_style:      {_fv(colors, style_name)}")
    print()


def _render_config(config: Config, colors: ColorManager) -> None:
    print(
        f"{colors.bold}Active Config{colors.reset}  "
        f"{colors.dim}(~/.claude/statusline.conf){colors.reset}"
    )
    for k, v in config.to_dict().items():
        if k == "color_overrides":
            if v:
                print(f"  {k}:")
                for slot, ansi_code in v.items():
                    print(f"    {slot}: {ansi_code}████{colors.reset}")
            continue
        print(f"  {k}: {v}")
    print()


def _render_raw_json(data: dict, colors: ColorManager) -> None:
    print(f"{colors.bold}Raw JSON{colors.reset}")
    print(f"{colors.dim}{json.dumps(data, indent=2)}{colors.reset}")
    print()


def run_explain(data: dict, no_color: bool = False) -> None:
    """Print a diagnostic dump of the Claude Code session JSON.

    Args:
        data: Parsed JSON dict from stdin.
        no_color: If True, suppress ANSI color codes.
    """
    config = Config.load()

    # Respect --no-color flag and non-TTY output
    color_enabled = not no_color and sys.stdout.isatty()
    colors = ColorManager(enabled=color_enabled, overrides=config.color_overrides)

    print(f"\n{colors.bold}cc-context-stats explain{colors.reset}")
    print(f"{colors.dim}{'─' * 60}{colors.reset}")
    print(
        f"{colors.dim}Shows how cc-context-stats interprets Claude Code's JSON context."
        f"{colors.reset}\n"
    )

    _render_model(data, colors)
    _render_workspace(data, colors)
    _render_context_window(data, colors, config)
    _render_cost(data, colors)
    _render_session(data, colors)
    _render_extensions(data, colors)
    _render_config(config, colors)
    _render_raw_json(data, colors)
