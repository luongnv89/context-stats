#!/usr/bin/env python3
"""
Python status line script for Claude Code
Usage: Copy to ~/.claude/statusline.py and make executable

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

State file format (CSV):
  timestamp,total_input_tokens,total_output_tokens,current_usage_input_tokens,current_usage_output_tokens,current_usage_cache_creation,current_usage_cache_read,total_cost_usd,total_lines_added,total_lines_removed,session_id,model_id,workspace_project_dir
"""

import json
import os
import re
import shutil
import subprocess
import sys

# ANSI Colors
BLUE = "\033[0;34m"
MAGENTA = "\033[0;35m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
DIM = "\033[2m"
RESET = "\033[0m"

# Pattern to strip ANSI escape sequences
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_width(s):
    """Return the visible width of a string after stripping ANSI escape sequences."""
    return len(_ANSI_RE.sub("", s))


def get_terminal_width():
    """Return the terminal width in columns, defaulting to 80."""
    return shutil.get_terminal_size().columns


def fit_to_width(parts, max_width):
    """Assemble parts into a single line that fits within max_width.

    Parts are added in priority order (first = highest priority).
    The first part (base) is always included. Subsequent parts are
    included only if adding them does not exceed max_width.
    Empty parts are skipped.
    """
    if not parts:
        return ""

    result = parts[0]
    current_width = visible_width(result)

    for part in parts[1:]:
        if not part:
            continue
        part_width = visible_width(part)
        if current_width + part_width <= max_width:
            result += part
            current_width += part_width

    return result


def get_git_info(project_dir):
    """Get git branch and change count"""
    git_dir = os.path.join(project_dir, ".git")
    if not os.path.isdir(git_dir):
        return ""

    try:
        # Get branch name (skip optional locks for performance)
        result = subprocess.run(
            ["git", "--no-optional-locks", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        branch = result.stdout.strip()

        if not branch:
            return ""

        # Count changes
        result = subprocess.run(
            ["git", "--no-optional-locks", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        changes = len([line for line in result.stdout.split("\n") if line.strip()])

        if changes > 0:
            return f" | {MAGENTA}{branch}{RESET} {CYAN}[{changes}]{RESET}"
        return f" | {MAGENTA}{branch}{RESET}"
    except Exception:
        return ""


def read_config():
    """Read settings from config file"""
    config = {
        "autocompact": True,
        "token_detail": True,
        "show_delta": True,
        "show_session": True,
        "show_io_tokens": True,
    }
    config_path = os.path.expanduser("~/.claude/statusline.conf")

    # Create config file with defaults if it doesn't exist
    if not os.path.exists(config_path):
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w") as f:
                f.write(
                    """# Autocompact setting - sync with Claude Code's /config
autocompact=true

# Token display format
token_detail=true

# Show token delta since last refresh (adds file I/O on every refresh)
# Disable if you don't need it to reduce overhead
show_delta=true

# Show session_id in status line
show_session=true
"""
                )
        except Exception:
            pass  # Ignore errors creating config
        return config

    try:
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().lower()
                if key == "autocompact":
                    config["autocompact"] = value != "false"
                elif key == "token_detail":
                    config["token_detail"] = value != "false"
                elif key == "show_delta":
                    config["show_delta"] = value != "false"
                elif key == "show_session":
                    config["show_session"] = value != "false"
                elif key == "show_io_tokens":
                    config["show_io_tokens"] = value != "false"
    except Exception:
        pass
    return config


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("[Claude] ~")
        return

    # Extract data
    cwd = data.get("workspace", {}).get("current_dir", "~")
    project_dir = data.get("workspace", {}).get("project_dir", cwd)
    model = data.get("model", {}).get("display_name", "Claude")
    dir_name = os.path.basename(cwd) or "~"

    # Git info
    git_info = get_git_info(project_dir)

    # Read settings from config file
    config = read_config()
    autocompact_enabled = config["autocompact"]
    token_detail = config["token_detail"]
    show_delta = config["show_delta"]
    show_session = config["show_session"]
    # Note: show_io_tokens setting is read but not yet implemented

    # Extract session_id once for reuse
    session_id = data.get("session_id")

    # Context window calculation
    context_info = ""
    ac_info = ""
    delta_info = ""
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

        # Calculate autocompact buffer (22.5% of context window = 45k for 200k)
        autocompact_buffer = int(total_size * 0.225)

        # Free tokens calculation depends on autocompact setting
        if autocompact_enabled:
            # When AC enabled: subtract buffer to show actual usable space
            free_tokens = total_size - used_tokens - autocompact_buffer
            buffer_k = autocompact_buffer // 1000
            ac_info = f" {DIM}[AC:{buffer_k}k]{RESET}"
        else:
            # When AC disabled: show full free space
            free_tokens = total_size - used_tokens
            ac_info = f" {DIM}[AC:off]{RESET}"

        if free_tokens < 0:
            free_tokens = 0

        # Calculate percentage with one decimal (relative to total size)
        free_pct = (free_tokens * 100.0) / total_size
        free_pct_int = int(free_pct)

        # Format tokens based on token_detail setting
        if token_detail:
            free_display = f"{free_tokens:,}"
        else:
            free_display = f"{free_tokens / 1000:.1f}k"

        # Color based on free percentage
        if free_pct_int > 50:
            ctx_color = GREEN
        elif free_pct_int > 25:
            ctx_color = YELLOW
        else:
            ctx_color = RED

        context_info = f" | {ctx_color}{free_display} free ({free_pct:.1f}%){RESET}"

        # Calculate and display token delta if enabled
        if show_delta:
            import glob
            import shutil
            import time

            state_dir = os.path.expanduser("~/.claude/statusline")
            os.makedirs(state_dir, exist_ok=True)

            old_state_dir = os.path.expanduser("~/.claude")
            for old_file in glob.glob(os.path.join(old_state_dir, "statusline*.state")):
                if os.path.isfile(old_file):
                    new_file = os.path.join(state_dir, os.path.basename(old_file))
                    if not os.path.exists(new_file):
                        shutil.move(old_file, new_file)
                    else:
                        os.remove(old_file)

            if session_id:
                state_file = os.path.join(state_dir, f"statusline.{session_id}.state")
            else:
                state_file = os.path.join(state_dir, "statusline.state")
            has_prev = False
            prev_tokens = 0
            try:
                if os.path.exists(state_file):
                    has_prev = True
                    # Read last line to get previous token count
                    with open(state_file) as f:
                        lines = f.readlines()
                        if lines:
                            last_line = lines[-1].strip()
                            if "," in last_line:
                                prev_tokens = int(last_line.split(",")[1])
                            else:
                                prev_tokens = int(last_line or 0)
            except Exception:
                prev_tokens = 0
            # Calculate delta
            delta = used_tokens - prev_tokens
            # Only show positive delta (and skip first run when no previous state)
            if has_prev and delta > 0:
                if token_detail:
                    delta_display = f"{delta:,}"
                else:
                    delta_display = f"{delta / 1000:.1f}k"
                delta_info = f" {DIM}[+{delta_display}]{RESET}"
            # Append current usage with comprehensive format
            # Format: timestamp,total_input_tokens,total_output_tokens,current_usage_input_tokens,current_usage_output_tokens,current_usage_cache_creation,current_usage_cache_read,total_cost_usd,total_lines_added,total_lines_removed,session_id,model_id,workspace_project_dir
            try:
                cur_input_tokens = current_usage.get("input_tokens", 0)
                cur_output_tokens = current_usage.get("output_tokens", 0)
                state_data = ",".join(
                    str(x)
                    for x in [
                        int(time.time()),
                        total_input_tokens,
                        total_output_tokens,
                        cur_input_tokens,
                        cur_output_tokens,
                        cache_creation,
                        cache_read,
                        cost_usd,
                        lines_added,
                        lines_removed,
                        session_id or "",
                        model_id,
                        workspace_project_dir,
                        total_size,
                    ]
                )
                with open(state_file, "a") as f:
                    f.write(f"{state_data}\n")
            except Exception:
                pass

    # Display session_id if enabled
    if show_session and session_id:
        session_info = f" {DIM}{session_id}{RESET}"

    # Output: [Model] directory | branch [changes] | XXk free (XX%) [+delta] [AC] [S:session_id]
    base = f"{DIM}[{model}]{RESET} {BLUE}{dir_name}{RESET}"
    max_width = get_terminal_width()
    parts = [base, git_info, context_info, delta_info, ac_info, session_info]
    print(fit_to_width(parts, max_width))


if __name__ == "__main__":
    main()
