#!/usr/bin/env python3
"""
Python status line script for Claude Code
Usage: Copy to ~/.claude/statusline.py and make executable

Configuration:
Create/edit ~/.claude/statusline.conf and set:

  autocompact=false  (when autocompact is disabled in Claude Code - default)
  autocompact=true   (when you enable autocompact via /config in Claude Code)

  token_detail=true  (show exact token count like 64,000 - default)
  token_detail=false (show abbreviated tokens like 64.0k)

  show_delta=true    (show token delta since last refresh like [+2,500] - default)
  show_delta=false   (disable delta display - saves file I/O on every refresh)

  show_session=true  (show session_id in status line - default)
  show_session=false (hide session_id from status line)

  show_pr=true   (show associated PR number like #42, requires gh CLI)
  show_pr=false  (hide PR number, default)

When AC is enabled, 22.5% of context window is reserved for autocompact buffer.

State file format (CSV):
  timestamp,total_input_tokens,total_output_tokens,current_usage_input_tokens,
  current_usage_output_tokens,current_usage_cache_creation,current_usage_cache_read,
  total_cost_usd,total_lines_added,total_lines_removed,session_id,model_id,
  workspace_project_dir,context_window_size,total_api_duration_ms
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROTATION_THRESHOLD = 10_000
ROTATION_KEEP = 5_000

# Model Intelligence color thresholds
MI_GREEN_THRESHOLD = 0.90
MI_YELLOW_THRESHOLD = 0.80
MI_CONTEXT_YELLOW = 0.40  # 40% context used
MI_CONTEXT_RED = 0.80  # 80% context used

# Per-model degradation profiles: beta controls curve shape
# Higher beta = quality retained longer (degradation happens later)
MODEL_PROFILES = {
    "opus": 1.8,
    "sonnet": 1.5,
    "haiku": 1.2,
    "default": 1.5,
}

# Zone indicator thresholds
LARGE_MODEL_THRESHOLD = 500_000  # >= 500k context = 1M-class model
# 1M thresholds recalibrated from observed context rot onset at 300-400k tokens.
# Source: x.com/trq212/status/2044548257058328723
ZONE_1M_P_MAX = 150_000  # P zone: < 150k used
ZONE_1M_C_MAX = 250_000  # C zone: 150k–250k used
ZONE_1M_D_MAX = 400_000  # D zone: 250k–400k used
ZONE_1M_X_MAX = 450_000  # X zone: 400k–450k used; Z zone: >= 450k
ZONE_STD_DUMP_ZONE = 0.40
ZONE_STD_WARN_BUFFER = 30_000
ZONE_STD_HARD_LIMIT = 0.70
ZONE_STD_DEAD_ZONE = 0.75

# Compaction detection defaults
COMPACTION_DROP_THRESHOLD = 0.5  # fraction of context that must be lost to count as compaction
COMPACT_MI_WARN_THRESHOLD = 0.6  # MI below this at compact time → warning

# Zone recommendation strings — one-line action guidance per zone
_ZONE_RECOMMENDATIONS = {
    "Plan": "Safe to plan and code",
    "Code": "Avoid starting new tasks; finish current one",
    "Dump": "Consider `/compact focus on X` or delegate to subagent",
    "ExDump": "Run `/compact` now before quality degrades further",
    "Dead": "Start a new session with `/clear`",
}


def get_model_profile(model_id):
    """Match model_id to degradation beta."""
    model_lower = (model_id or "").lower()
    for family in ("opus", "sonnet", "haiku"):
        if family in model_lower:
            return MODEL_PROFILES[family]
    return MODEL_PROFILES["default"]


def compute_mi(used_tokens, context_window_size, model_id="", beta_override=0.0):
    """Compute Model Intelligence score. Returns mi (float).

    MI(u) = max(0, 1 - u^beta) where beta is model-specific.
    """
    # Guard clause
    if context_window_size == 0:
        return 1.0

    beta_from_profile = get_model_profile(model_id)
    beta = beta_override if beta_override > 0 else beta_from_profile

    u = used_tokens / context_window_size
    if u <= 0:
        return 1.0
    return max(0.0, 1.0 - u**beta)


# Extra rows read beyond ``tps_window`` when tail-reading state history for
# tok/s. compute_tps needs the last ``tps_window`` valid *turns* (=
# ``tps_window + 1`` valid rows); this headroom absorbs the sparse, isolated
# dropped rows real histories contain (non-positive API-time delta, zero
# output) plus any legacy/blank rows, so the rendered value matches a
# full-history read. Kept small so each refresh still parses only a bounded
# tail. Legacy rows (no api_duration) can only be a leading prefix once tok/s
# is enabled. Mirrors cli/statusline.py:_TPS_TAIL_BUFFER.
_TPS_TAIL_BUFFER = 8


def _tps_tail_size(tps_window):
    """Number of trailing state rows to read for the tok/s rolling average.

    ``tps_window`` valid turns need ``tps_window + 1`` valid rows; doubling the
    window plus a fixed buffer leaves ample room for interleaved dropped rows
    while staying bounded (independent of total file size). Mirrors the package
    helper cli/statusline.py:_tps_tail_size.
    """
    return max(1, tps_window) * 2 + _TPS_TAIL_BUFFER


def compute_tps(samples, window=5):
    """Compute a smoothed, session-rolling model throughput in tokens/second.

    Rather than the jumpy per-turn instantaneous speed (which swings between,
    say, 1.5 and 80 tok/s depending on how many tokens a turn happened to
    emit), this returns a rolling, token-weighted average over the most recent
    turns. Weighting by output tokens means a tiny 3-token turn cannot drag the
    number down the way a plain mean-of-ratios would — the result tracks the
    genuine "speed of the model" across the session.

    Each sample is an (output_tokens, api_duration_ms) pair from a state row
    (plus the live reading), where api_duration_ms is the cumulative
    cost.total_api_duration_ms ("time spent waiting for API responses" — it
    excludes user idle time, tool execution, and thinking). A *turn* is the
    transition between two consecutive samples: its output is that row's
    current_usage.output_tokens and its API time is the delta of the
    cumulative durations. Turns with a non-positive API-time delta (same
    response refreshed twice) or non-positive output are dropped.

    Average over the last `window` valid turns, token-weighted:

        tok/s = sum(output) / (sum(api_time_ms) / 1000)

    A turn that contributes no valid sample simply isn't in the sums, so the
    previously established average persists ("keep last average" on missing
    data) as long as one valid turn remains in the window.

    Returns tokens/second, or None when no valid turn exists yet (first row,
    all legacy rows, or no real API time elapsed) — None means "hide".
    """
    if window < 1:
        window = 1
    turns = []
    for i in range(1, len(samples)):
        prev_dur = samples[i - 1][1]
        out, cur_dur = samples[i]
        # A zero/negative previous cumulative means a legacy row without the
        # field — differencing against it would understate throughput badly.
        if prev_dur <= 0:
            continue
        delta_ms = cur_dur - prev_dur
        if delta_ms <= 0 or out <= 0:
            continue
        turns.append((out, delta_ms))
    if not turns:
        return None
    recent = turns[-window:]
    total_output = sum(out for out, _ in recent)
    total_ms = sum(ms for _, ms in recent)
    if total_ms <= 0:
        return None
    return total_output / (total_ms / 1000.0)


def format_tps(tps, precision=1, unit="tok/s"):
    """Format a tokens-per-second value for display (e.g. '42.5 tok/s')."""
    precision = min(10, max(0, precision))
    return f"{tps:.{precision}f} {unit}"


def get_mi_color(mi, utilization=0.0):
    """Return ANSI color code for MI score considering both MI and context utilization."""
    if mi <= MI_YELLOW_THRESHOLD or utilization >= MI_CONTEXT_RED:
        return RED
    if mi < MI_GREEN_THRESHOLD or utilization >= MI_CONTEXT_YELLOW:
        return YELLOW
    return GREEN


def get_context_zone(used_tokens, context_window_size, zone_config=None):
    """Determine context zone indicator based on token usage.

    Returns (zone_word, color_name, recommendation) tuple.
    zone_config is an optional dict of threshold overrides (0 = use default).
    """
    if context_window_size == 0:
        return ("Plan", "green", _ZONE_RECOMMENDATIONS["Plan"])

    zc = zone_config or {}

    lmt = zc.get("large_model_threshold") or LARGE_MODEL_THRESHOLD
    is_large = context_window_size >= lmt

    if is_large:
        p_max = zc.get("zone_1m_plan_max") or ZONE_1M_P_MAX
        c_max = zc.get("zone_1m_code_max") or ZONE_1M_C_MAX
        d_max = zc.get("zone_1m_dump_max") or ZONE_1M_D_MAX
        x_max = zc.get("zone_1m_xdump_max") or ZONE_1M_X_MAX

        if used_tokens < p_max:
            return ("Plan", "green", _ZONE_RECOMMENDATIONS["Plan"])
        if used_tokens < c_max:
            return ("Code", "yellow", _ZONE_RECOMMENDATIONS["Code"])
        if used_tokens < d_max:
            return ("Dump", "orange", _ZONE_RECOMMENDATIONS["Dump"])
        if used_tokens < x_max:
            return ("ExDump", "dark_red", _ZONE_RECOMMENDATIONS["ExDump"])
        return ("Dead", "gray", _ZONE_RECOMMENDATIONS["Dead"])

    dump_ratio = zc.get("zone_std_dump_ratio") or ZONE_STD_DUMP_ZONE
    warn_buf = zc.get("zone_std_warn_buffer") or ZONE_STD_WARN_BUFFER
    hard_lim = zc.get("zone_std_hard_limit") or ZONE_STD_HARD_LIMIT
    dead_rat = zc.get("zone_std_dead_ratio") or ZONE_STD_DEAD_ZONE

    dump_zone_tokens = int(context_window_size * dump_ratio)
    warn_start = max(0, dump_zone_tokens - warn_buf)
    hard_limit_tokens = int(context_window_size * hard_lim)
    dead_zone_tokens = int(context_window_size * dead_rat)

    if used_tokens < warn_start:
        return ("Plan", "green", _ZONE_RECOMMENDATIONS["Plan"])
    if used_tokens < dump_zone_tokens:
        return ("Code", "yellow", _ZONE_RECOMMENDATIONS["Code"])
    if used_tokens < hard_limit_tokens:
        return ("Dump", "orange", _ZONE_RECOMMENDATIONS["Dump"])
    if used_tokens < dead_zone_tokens:
        return ("ExDump", "dark_red", _ZONE_RECOMMENDATIONS["ExDump"])
    return ("Dead", "gray", _ZONE_RECOMMENDATIONS["Dead"])


def detect_compaction_events(values, drop_threshold=None):
    """Detect compaction events in a list of token counts.

    A compaction event is identified when ``values[i] < values[i-1] * (1 - drop_threshold)``,
    i.e., the context dropped by more than *drop_threshold* fraction in a single step.

    Args:
        values: Sequence of token counts (e.g., current_used_tokens over time).
        drop_threshold: Fraction of context that must be lost to qualify as compaction
                        (default: COMPACTION_DROP_THRESHOLD = 0.5).

    Returns:
        List of indices i (into values) where a compaction was detected.
    """
    if drop_threshold is None:
        drop_threshold = COMPACTION_DROP_THRESHOLD
    if len(values) < 2:
        return []
    events = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        curr = values[i]
        if prev > 0 and curr < prev * (1.0 - drop_threshold):
            events.append(i)
    return events


def _zone_ansi_color(color_name):
    """Map zone color name to ANSI escape code."""
    if color_name == "green":
        return GREEN
    if color_name == "yellow":
        return YELLOW
    if color_name == "orange":
        return "\033[38;2;255;165;0m"  # RGB orange
    if color_name == "dark_red":
        return "\033[38;2;139;0;0m"  # RGB dark red
    if color_name == "gray":
        return "\033[0;90m"  # bright black / gray
    return RESET


def maybe_rotate_state_file(state_file):
    """Rotate a state file if it exceeds ROTATION_THRESHOLD lines.

    Keeps the most recent ROTATION_KEEP lines via atomic temp-file + rename.
    """
    try:
        if not os.path.exists(state_file):
            return
        with open(state_file) as f:
            lines = f.readlines()
        if len(lines) <= ROTATION_THRESHOLD:
            return
        keep = lines[-ROTATION_KEEP:]
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(state_file), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as tmp_f:
                tmp_f.writelines(keep)
            os.replace(tmp_path, state_file)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        sys.stderr.write(f"[statusline] warning: failed to rotate state file: {e}\n")


# ANSI Colors (defaults, overridable via config)
BLUE = "\033[0;34m"
MAGENTA = "\033[0;35m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
DIM = "\033[2m"
RESET = "\033[0m"

# Named colors for config parsing
_COLOR_NAMES = {
    "black": "\033[0;30m",
    "red": "\033[0;31m",
    "green": "\033[0;32m",
    "yellow": "\033[0;33m",
    "blue": "\033[0;34m",
    "magenta": "\033[0;35m",
    "cyan": "\033[0;36m",
    "white": "\033[0;37m",
    "bright_black": "\033[0;90m",
    "bright_red": "\033[0;91m",
    "bright_green": "\033[0;92m",
    "bright_yellow": "\033[0;93m",
    "bright_blue": "\033[0;94m",
    "bright_magenta": "\033[0;95m",
    "bright_cyan": "\033[0;96m",
    "bright_white": "\033[0;97m",
    "bold_white": "\033[1;97m",
    "dim": "\033[2m",
}


def _parse_color(value):
    """Parse a color name or #rrggbb hex into an ANSI escape code."""
    value = value.strip().lower()
    if value in _COLOR_NAMES:
        return _COLOR_NAMES[value]
    if re.match(r"^#[0-9a-f]{6}$", value):
        r, g, b = int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
        return f"\033[38;2;{r};{g};{b}m"
    return None


# Color config keys and which color slot they map to
_COLOR_KEYS = {
    "color_green": "green",
    "color_yellow": "yellow",
    "color_red": "red",
    "color_blue": "blue",
    "color_magenta": "magenta",
    "color_cyan": "cyan",
    # Per-property color keys
    "color_context_length": "context_length",
    "color_project_name": "project_name",
    "color_branch_name": "branch_name",
    "color_mi_score": "mi_score",
    "color_zone": "zone",
    "color_separator": "separator",
    "color_tps": "tps",
    "color_delta": "delta",
    "color_cost": "cost",
    "color_model": "model",
    "color_session": "session",
}

# Zone threshold config keys (integer token counts)
_ZONE_INT_KEYS = {
    "zone_1m_plan_max",
    "zone_1m_code_max",
    "zone_1m_dump_max",
    "zone_1m_xdump_max",
    "zone_std_warn_buffer",
    "large_model_threshold",
}

# Zone threshold config keys (float ratios 0-1)
_ZONE_FLOAT_KEYS = {
    "zone_std_dump_ratio",
    "zone_std_hard_limit",
    "zone_std_dead_ratio",
}

# Pattern to strip ANSI escape sequences
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_width(s):
    """Return the visible width of a string after stripping ANSI escape sequences."""
    return len(_ANSI_RE.sub("", s))


def get_terminal_width():
    """Return the terminal width in columns.

    When running inside Claude Code's statusline subprocess, neither $COLUMNS
    nor tput/shutil can detect the real terminal width (they always return 80).
    If COLUMNS is not explicitly set and shutil falls back to 80, we use a
    generous default of 200 so that no parts are unnecessarily dropped;
    Claude Code's own UI handles any overflow/truncation.
    """
    # If COLUMNS is explicitly set, trust it (real terminal or test override)
    if os.environ.get("COLUMNS"):
        return shutil.get_terminal_size().columns
    # No COLUMNS env var — likely a Claude Code subprocess with no real TTY.
    # shutil will fall back to 80, which is too narrow. Use 200 instead.
    cols = shutil.get_terminal_size(fallback=(200, 24)).columns
    return 200 if cols == 80 else cols


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


def get_pr_number(project_dir: str) -> str:
    """Look up the PR number for the current branch via gh CLI.

    Returns a formatted string like ``#42`` when an open PR exists,
    or an empty string when no PR is associated or gh CLI is unavailable.
    """
    if shutil.which("gh") is None:
        return ""

    try:
        branch = subprocess.run(
            ["git", "--no-optional-locks", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch.returncode != 0:
            return ""
        branch_name = branch.stdout.strip()
        if not branch_name:
            return ""

        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch_name,
                "--state",
                "open",
                "--json",
                "number",
                "--limit",
                "1",
            ],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ""

        try:
            data = json.loads(result.stdout.strip())
        except (json.JSONDecodeError, ValueError):
            return ""

        if data and len(data) > 0:
            pr_num = data[0].get("number", "")
            if pr_num:
                return f"#{pr_num}"
        return ""
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return ""


def get_git_info(project_dir, magenta=None, cyan=None):
    """Get git branch and change count"""
    if magenta is None:
        magenta = MAGENTA
    if cyan is None:
        cyan = CYAN
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
            timeout=5,
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
            timeout=5,
        )
        changes = len([line for line in result.stdout.split("\n") if line.strip()])

        if changes > 0:
            return f" | {magenta}{branch}{RESET} {cyan}[{changes}]{RESET}"
        return f" | {magenta}{branch}{RESET}"
    except (subprocess.TimeoutExpired, OSError):
        return ""


def read_config():
    """Read settings from config file"""
    config = {
        "autocompact": False,
        "token_detail": True,
        "show_delta": True,
        "show_session": True,
        "show_io_tokens": True,
        "reduced_motion": False,
        "show_mi": False,
        "mi_curve_beta": 0.0,
        "show_tps": False,
        "tps_precision": 1,
        "tps_unit": "tok/s",
        "tps_window": 5,
        "show_pr": False,
        "show_cost": True,
        "colors": {},
        "zone_config": {},
        "compaction_drop_threshold": COMPACTION_DROP_THRESHOLD,
        "compact_mi_warn_threshold": COMPACT_MI_WARN_THRESHOLD,
    }
    config_path = os.path.expanduser("~/.claude/statusline.conf")

    # Create config file with defaults if it doesn't exist
    if not os.path.exists(config_path):
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(
                    """\
# ============================================================================
# context-stats — statusline configuration
# ============================================================================
#
# Copy this file to:   ~/.claude/statusline.conf
# Windows:             %USERPROFILE%\\.claude\\statusline.conf
#
# Full reference:
#   https://github.com/luongnv89/cc-context-stats/blob/main/docs/configuration.md
#
# Format:
#   - key=value (no spaces around '=')
#   - Lines starting with '#' are comments
#   - Unrecognized keys are silently ignored
#   - Missing or invalid values fall back to built-in defaults
#
# ============================================================================


# ─── Display Settings ───────────────────────────────────────────────────────
#
# These boolean flags control which elements appear in the statusline.
# Any value other than "false" (case-insensitive) is treated as true.

# Autocompact buffer display.
# When true, 22.5% of the context window is reserved for Claude Code's
# autocompact feature. This affects the "free tokens" calculation.
# Must match your Claude Code setting — check with: /config
#   true  -> shows [AC:45k] buffer in statusline
#   false -> shows [AC:off]
autocompact=false

# Token display format.
#   true  = exact count with commas (e.g., 64,000 free)
#   false = abbreviated with suffix  (e.g., 64.0k free)
# Also affects the delta display (+2,500 vs +2.5k).
token_detail=true

# Show token delta since last refresh (e.g., +2,500).
# Displays how many tokens were consumed since the previous statusline update.
# Requires file I/O on every refresh to read the previous state.
# Disable if you want to reduce disk overhead.
show_delta=true

# Show the session ID at the end of the statusline.
# Useful when running multiple Claude Code instances to identify sessions.
# Double-click in terminal to select and copy.
show_session=true

# Show input/output token breakdown.
# Reserved for future use — currently read but not displayed.
show_io_tokens=true

# Disable rotating text and icon animations for accessibility.
#   false = animations enabled (default)
#   true  = static display, no motion
reduced_motion=false

# Show the associated PR number for the current branch in the statusline.
# Uses the GitHub CLI (gh) to look up open PRs. Requires gh to be installed.
#   false = PR number hidden (default)
#   true  = PR number visible (e.g., #42)
show_pr=false

# Show the cumulative session cost in USD (e.g., $0.42).
# Cost is reported by Claude Code (cost.total_cost_usd); the value is the
# running total for the whole session, shown even at $0.00.
#   true  = cost visible (default)
#   false = cost hidden
show_cost=true


# ─── Model Intelligence (MI) ────────────────────────────────────────────────
#
# MI measures how effectively the model uses its context window. The score
# ranges from 0.000 (fully degraded) to 1.000 (optimal). As context fills,
# MI degrades following a model-specific curve.

# Show the MI score in the statusline (e.g., MI:0.918).
# When enabled, also requires state file I/O for tracking.
#   false = MI score hidden (default)
#   true  = MI score visible
show_mi=false

# Override the MI degradation curve beta for all models.
# Each model has a built-in profile that controls how quickly MI degrades:
#   opus   = 1.8  (retains quality longest, steep drop near end)
#   sonnet = 1.5  (moderate degradation)
#   haiku  = 1.2  (degrades earliest)
# Set to 0 to use the model-specific profile (recommended).
# Set a positive value (e.g., 1.5) to override for all models.
mi_curve_beta=0


# ─── Model Throughput (tok/s) ───────────────────────────────────────────────
#
# Displays the model's generation speed in tokens per second (e.g., 42.5 tok/s).
# Speed is measured from the time spent waiting for API responses
# (cost.total_api_duration_ms), so it reflects pure model throughput and
# excludes your idle time, tool execution, and thinking.
#
# The value is a rolling, token-weighted average over the last few turns (see
# tps_window), not the raw per-turn speed — per-turn speed swings wildly (a
# 3-token reply looks like 1.5 tok/s, a long answer like 80 tok/s), so the
# average is far steadier and tracks the genuine "speed of the model". Once
# established it persists across turns that carry no new timing info.
#
# Like MI, this requires state file I/O for tracking across refreshes.

# Show model throughput in the statusline (e.g., 42.5 tok/s).
#   false = throughput hidden (default)
#   true  = throughput visible
show_tps=false

# Number of decimal places for the throughput value.
#   0 -> "42 tok/s"
#   1 -> "42.5 tok/s" (default)
#   2 -> "42.53 tok/s"
tps_precision=1

# Unit label appended after the throughput value.
#   tok/s    (default)
#   tokens/s (more explicit)
tps_unit=tok/s

# Number of recent turns averaged for the rolling throughput.
#   Larger  = steadier, slower to react to a speed change.
#   Smaller = more responsive, slightly jumpier. Minimum 1.
#   5 = default
tps_window=5


# ─── Zone Threshold Overrides ───────────────────────────────────────────────
#
# Zones indicate how much context pressure your session is under:
#   Plan   (P) = plenty of room, ideal for planning and exploration
#   Code   (C) = normal coding zone, context is filling but healthy
#   Dump   (D) = getting full, consider wrapping up or starting fresh
#   ExDump (X) = critical, autocompact may trigger, quality degrading
#   Dead   (Z) = context exhausted, start a new session
#
# There are two threshold sets: one for large models (1M+ context) using
# absolute token counts, and one for standard models using ratios (0-1).
#
# Uncomment and set a positive value to override the built-in defaults.
# Invalid values (negative, non-numeric, ratios outside 0-1) are ignored
# with a warning to stderr.

# Context windows >= this value use 1M-class thresholds (token count).
# Models below this threshold use the standard ratio-based zones.
# large_model_threshold=500000

# --- 1M-Class Models (context >= large_model_threshold) ---
# Values are absolute token counts for zone boundaries (tokens used).
# zone_1m_plan_max=70000       # Plan -> Code boundary
# zone_1m_code_max=100000      # Code -> Dump boundary
# zone_1m_dump_max=250000      # Dump -> ExDump boundary
# zone_1m_xdump_max=275000     # ExDump -> Dead boundary

# --- Standard Models (context < large_model_threshold) ---
# Ratios are 0-1 fractions of the total context window.
# zone_std_dump_ratio=0.40     # Dump zone starts at 40% utilization
# zone_std_warn_buffer=30000   # Show warning this many tokens before dump zone
# zone_std_hard_limit=0.70     # Hard limit at 70% utilization
# zone_std_dead_ratio=0.75     # Dead zone starts at 75% utilization


# ─── Base Color Slots ───────────────────────────────────────────────────────
#
# Override the 6 base palette colors used for MI-based traffic-light coloring
# and as fallbacks for per-property colors (see next section).
#
# Accepts named colors or hex codes (#rrggbb).
#
# Named colors (18 available):
#   Standard:  black, red, green, yellow, blue, magenta, cyan, white
#   Bright:    bright_black, bright_red, bright_green, bright_yellow,
#              bright_blue, bright_magenta, bright_cyan, bright_white
#   Special:   bold_white, dim
#
# Hex colors: any #rrggbb value (requires 24-bit color terminal support)
#
# Unrecognized values are ignored with a warning to stderr.

# Traffic-light colors — used for MI score and context zone indicators.
# Colors are determined by BOTH MI score and context utilization:
#   color_green  -> MI >= 0.90 AND context < 40% (model operating well)
#   color_yellow -> MI in (0.80, 0.90) OR context in [40%, 80%) (pressure building)
#   color_red    -> MI <= 0.80 OR context >= 80% (significant degradation)
color_green=#7dcfff
color_yellow=#e0af68
color_red=#f7768e

# Legacy element fallback colors:
#   color_blue    -> fallback for project name (if color_project_name not set)
#   color_magenta -> fallback for branch name (if color_branch_name not set)
#   color_cyan    -> git change-count brackets (e.g., [3])
color_blue=#7aa2f7
color_magenta=#bb9af7
color_cyan=#2ac3de


# ─── Per-Property Colors ────────────────────────────────────────────────────
#
# Override individual statusline elements. These take precedence over
# base color slots above.
#
# Fallback chain: per-property key -> base color slot -> built-in default
#
# For example, if color_project_name is not set, it falls back to color_blue
# (if set), then to the built-in cyan.

# Context tokens remaining — the most critical info.
# When not set, uses zone traffic-light color (green/yellow/red) automatically.
# Set explicitly to use a fixed color regardless of zone.
# color_context_length=bold_white

# Project directory name (e.g., "my-project").
color_project_name=bright_cyan

# Git branch name (e.g., "main").
color_branch_name=bright_magenta

# MI score display (e.g., "MI:0.918").
# When not set, uses MI-based traffic-light color automatically.
color_mi_score=#ff9e64

# Zone indicator label (e.g., "Plan", "Code", "Dump").
# When not set, uses zone traffic-light color automatically.
# color_zone=bright_green

# Structural elements: tok/s, token delta, model name, session ID.
# "dim" makes these visually recede so primary info stands out.
color_separator=dim

# Each structural element can also be colored independently. When unset, they
# inherit color_separator above. Uncomment to give any of them its own color
# (named colors or #rrggbb), so every value in the statusline can be distinct.
# Keep the value alone on the line — trailing inline comments are not stripped.
# model throughput (e.g. "42.5 tok/s")
# color_tps=#6ED7D2
# token delta since last refresh (e.g. "+2,500")
# color_delta=#FFF8DC
# model name (e.g. "Opus 4.8")
# color_model=#C0C0C0
# session ID shown at the end
# color_session=#8B8682


# ─── Statusline Layout Reference ────────────────────────────────────────────
#
# The statusline elements are displayed in this order (highest priority first):
#
#   project_name | branch [changes] | tokens_free (%) | Zone | MI:score | tok/s | +delta | Model | session_id
#
# Example output:
#   my-project | main [3] | 64,000 free (32.0%) | Code | MI:0.918 | 42.5 tok/s | +2,500 | Opus 4.6 | abc-123
#
# If the terminal is too narrow, lower-priority elements are dropped:
#   1. session_id   (dropped first)
#   2. model name
#   3. token delta
#   4. tok/s throughput
#   5. MI score
#   6. zone indicator
#   7. context info
#   8. git info
#   9. project name  (always shown, never dropped)
"""
                )
        except Exception as e:
            sys.stderr.write(f"[statusline] warning: failed to create config: {e}\n")
            return config

    if not os.path.exists(config_path):
        return config

    try:
        with open(config_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                raw_value = value.strip()
                value_lower = raw_value.lower()
                if key == "autocompact":
                    config["autocompact"] = value_lower != "false"
                elif key == "token_detail":
                    config["token_detail"] = value_lower != "false"
                elif key == "show_delta":
                    config["show_delta"] = value_lower != "false"
                elif key == "show_session":
                    config["show_session"] = value_lower != "false"
                elif key == "show_io_tokens":
                    config["show_io_tokens"] = value_lower != "false"
                elif key == "reduced_motion":
                    config["reduced_motion"] = value_lower != "false"
                elif key == "show_mi":
                    config["show_mi"] = value_lower != "false"
                elif key == "mi_curve_beta":
                    try:
                        config["mi_curve_beta"] = float(raw_value)
                    except ValueError:
                        pass
                elif key == "show_tps":
                    config["show_tps"] = value_lower != "false"
                elif key == "show_pr":
                    config["show_pr"] = value_lower != "false"
                elif key == "show_cost":
                    config["show_cost"] = value_lower != "false"
                elif key == "tps_precision":
                    try:
                        v = int(raw_value)
                        if v >= 0:
                            config["tps_precision"] = v
                        else:
                            sys.stderr.write(
                                f"[statusline] warning: tps_precision must be >= 0, "
                                f"ignoring '{raw_value}'\n"
                            )
                    except ValueError:
                        sys.stderr.write(
                            f"[statusline] warning: invalid integer for tps_precision: "
                            f"'{raw_value}'\n"
                        )
                elif key == "tps_unit":
                    if raw_value:
                        config["tps_unit"] = raw_value
                elif key == "tps_window":
                    try:
                        v = int(raw_value)
                        if v >= 1:
                            config["tps_window"] = v
                        else:
                            sys.stderr.write(
                                f"[statusline] warning: tps_window must be >= 1, "
                                f"ignoring '{raw_value}'\n"
                            )
                    except ValueError:
                        sys.stderr.write(
                            f"[statusline] warning: invalid integer for tps_window: '{raw_value}'\n"
                        )
                elif key in _COLOR_KEYS:
                    ansi = _parse_color(raw_value)
                    if ansi:
                        config["colors"][_COLOR_KEYS[key]] = ansi
                elif key in _ZONE_INT_KEYS:
                    try:
                        v = int(raw_value)
                        if v > 0:
                            config["zone_config"][key] = v
                        else:
                            sys.stderr.write(
                                f"[statusline] warning: {key} must be positive, "
                                f"ignoring '{raw_value}'\n"
                            )
                    except ValueError:
                        sys.stderr.write(
                            f"[statusline] warning: invalid integer for {key}: '{raw_value}'\n"
                        )
                elif key in _ZONE_FLOAT_KEYS:
                    try:
                        v = float(raw_value)
                        if 0.0 < v < 1.0:
                            config["zone_config"][key] = v
                        else:
                            sys.stderr.write(
                                f"[statusline] warning: {key} must be between 0 and 1, "
                                f"ignoring '{raw_value}'\n"
                            )
                    except ValueError:
                        sys.stderr.write(
                            f"[statusline] warning: invalid number for {key}: '{raw_value}'\n"
                        )
                elif key in ("compaction_drop_threshold", "compact_mi_warn_threshold"):
                    try:
                        v = float(raw_value)
                        if 0.0 < v < 1.0:
                            config[key] = v
                        else:
                            sys.stderr.write(
                                f"[statusline] warning: {key} must be between 0 and 1, "
                                f"ignoring '{raw_value}'\n"
                            )
                    except ValueError:
                        sys.stderr.write(
                            f"[statusline] warning: invalid number for {key}: '{raw_value}'\n"
                        )
    except (OSError, UnicodeDecodeError) as e:
        sys.stderr.write(f"[statusline] warning: failed to read config: {e}\n")
    return config


def _format_thinking_info(budget) -> str:
    """Format thinking budget for display next to model name.

    Returns an empty string when budget is None or zero.
    Small budgets (< 1000) are shown exactly.
    Medium budgets (1000–9999) are shown as "Nk" only when rounding is reasonable (>= 5k).
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


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.stdout.write("[Claude] ~\n")
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
    dir_name = os.path.basename(cwd) or "~"

    # Read settings from config file
    config = read_config()
    autocompact_enabled = config["autocompact"]
    token_detail = config["token_detail"]
    show_delta = config["show_delta"]
    show_session = config["show_session"]
    show_mi = config["show_mi"]
    mi_curve_beta = config["mi_curve_beta"]
    show_tps = config["show_tps"]
    tps_precision = config["tps_precision"]
    tps_unit = config["tps_unit"]
    tps_window = config["tps_window"]
    show_pr = config["show_pr"]
    show_cost = config["show_cost"]
    # Note: show_io_tokens setting is read but not yet implemented

    # Apply color overrides from config
    c = config.get("colors", {})
    # Color overrides applied via module globals for MI/context coloring
    # pylint: disable=global-statement
    global GREEN, YELLOW, RED  # noqa: PLW0603
    GREEN = c.get("green", GREEN)
    YELLOW = c.get("yellow", YELLOW)
    RED = c.get("red", RED)
    c_blue = c.get("blue", BLUE)
    c_magenta = c.get("magenta", MAGENTA)
    c_cyan = c.get("cyan", CYAN)

    # Per-property color defaults (highlighted key info)
    # Falls back to old color keys for backward compatibility, then to new defaults
    c_project_name = c.get("project_name", c_blue if "blue" in c else CYAN)
    c_branch_name = c.get("branch_name", c_magenta if "magenta" in c else GREEN)
    c_separator = c.get("separator", DIM)

    # Structural elements default to the separator color, but each can be
    # overridden independently (color_tps / color_delta / color_model / color_session).
    c_tps = c.get("tps", c_separator)
    c_delta = c.get("delta", c_separator)
    c_cost = c.get("cost", c_separator)
    c_model = c.get("model", c_separator)
    c_session = c.get("session", c_separator)

    # Git info (use per-property branch color, fallback to green)
    git_info = get_git_info(project_dir, magenta=c_branch_name, cyan=c_cyan)

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

    # PR number lookup
    if show_pr:
        pr_num = get_pr_number(project_dir)
        if pr_num:
            pr_info = f" | {c_separator}{pr_num}{RESET}"
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

        # Calculate autocompact buffer (22.5% of context window = 45k for 200k)
        autocompact_buffer = int(total_size * 0.225)

        # Free tokens calculation depends on autocompact setting
        if autocompact_enabled:
            free_tokens = total_size - used_tokens - autocompact_buffer
        else:
            free_tokens = total_size - used_tokens

        if free_tokens < 0:
            free_tokens = 0

        # Calculate percentage with one decimal (relative to total size)
        free_pct = (free_tokens * 100.0) / total_size

        # Format tokens based on token_detail setting
        if token_detail:
            free_display = f"{free_tokens:,}"
        else:
            free_display = f"{free_tokens / 1000:.1f}k"

        # Zone indicator — determines color for both context info and zone label
        zone_word, zone_color_name, zone_recommendation = get_context_zone(
            used_tokens, total_size, config.get("zone_config")
        )
        zone_ansi = _zone_ansi_color(zone_color_name)

        # Context info uses zone color (traffic-light), with per-property override
        effective_ctx_color = c.get("context_length", zone_ansi)

        context_info = f" | {effective_ctx_color}{free_display} ({free_pct:.1f}%){RESET}"

        # Zone label uses same color, with per-property override
        effective_zone_color = c.get("zone", zone_ansi)
        zone_info = f" | {effective_zone_color}{zone_word}{RESET}"

        # Read previous entry if needed for delta, MI, or throughput (tok/s).
        # tok/s needs the previous row (for the API-time delta) and persists
        # the current api_duration for the next refresh, so it widens this gate.
        if show_delta or show_mi or show_tps:
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
            # Rolling tok/s samples: (output_tokens, api_duration_ms) per row,
            # in chronological order. Only collected when show_tps is on.
            tps_samples = []
            try:
                if os.path.exists(state_file):
                    has_prev = True
                    # Read all lines: last line drives delta/dedup; a bounded
                    # *tail* (when show_tps) feeds the rolling-average
                    # reconstruction. compute_tps only needs the last
                    # ``tps_window`` valid turns, so we parse at most the last
                    # ``_tps_tail_size(tps_window)`` rows instead of the whole
                    # file — matching the full-read value while bounding work.
                    with open(state_file) as f:
                        file_lines = f.readlines()
                        if file_lines:
                            last_line = file_lines[-1].strip()
                            if "," in last_line:
                                csv_parts = last_line.split(",")
                                # Calculate previous context usage:
                                # cur_input + cache_creation + cache_read
                                # CSV indices: cur_in[3], cache_create[5], cache_read[6]
                                prev_cur_input = int(csv_parts[3]) if len(csv_parts) > 3 else 0
                                prev_cache_creation = int(csv_parts[5]) if len(csv_parts) > 5 else 0
                                prev_cache_read = int(csv_parts[6]) if len(csv_parts) > 6 else 0
                                prev_tokens = prev_cur_input + prev_cache_creation + prev_cache_read
                            else:
                                # Old format - single value
                                prev_tokens = int(last_line or 0)
                            if show_tps:
                                # Reconstruct (output[4], api_duration[14]) for
                                # each tail row. Legacy rows lack index 14 -> 0,
                                # which compute_tps treats as "no prior reading".
                                # Walk backward collecting up to tail_n parseable
                                # rows (mirrors StateFile.read_tail's by-entry
                                # bound), then restore chronological order.
                                tail_n = _tps_tail_size(tps_window)
                                for line in reversed(file_lines):
                                    parts = line.strip().split(",")
                                    if len(parts) < 5:
                                        continue
                                    try:
                                        out = int(parts[4])
                                        dur = int(parts[14]) if len(parts) > 14 else 0
                                    except ValueError:
                                        continue
                                    tps_samples.append((out, dur))
                                    if len(tps_samples) >= tail_n:
                                        break
                                tps_samples.reverse()
            except (OSError, ValueError) as e:
                sys.stderr.write(f"[statusline] warning: failed to read state file: {e}\n")
                prev_tokens = 0
                tps_samples = []

            # Calculate and display token delta if enabled
            if show_delta:
                delta = used_tokens - prev_tokens
                if has_prev and delta > 0:
                    if token_detail:
                        delta_display = f"{delta:,}"
                    else:
                        delta_display = f"{delta / 1000:.1f}k"
                    delta_info = f" | {c_delta}+{delta_display}{RESET}"

            # Calculate and display MI score if enabled
            if show_mi:
                mi_val = compute_mi(used_tokens, total_size, model_id, mi_curve_beta)
                mi_util = used_tokens / total_size if total_size > 0 else 0.0
                mi_color = get_mi_color(mi_val, mi_util)
                # Use per-property mi_score color if configured, else MI-based color
                effective_mi_color = c.get("mi_score", mi_color)
                mi_info = f" | {effective_mi_color}MI:{mi_val:.3f}{RESET}"

            # Calculate and display model throughput (tok/s) if enabled — a
            # rolling, token-weighted average over the last N turns from the
            # state history plus the live reading.
            if show_tps:
                cur_output = current_usage.get("output_tokens", 0)
                samples = tps_samples + [(cur_output, api_duration_ms)]
                tps = compute_tps(samples, window=tps_window)
                if tps is not None:
                    tps_display = format_tps(tps, tps_precision, tps_unit)
                    tps_info = f" | {c_tps}{tps_display}{RESET}"

            # Only append if context usage changed (avoid duplicates from multiple refreshes)
            if not has_prev or used_tokens != prev_tokens:
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
                            workspace_project_dir.replace(",", "_"),
                            total_size,
                            api_duration_ms,
                        ]
                    )
                    with open(state_file, "a") as f:
                        f.write(f"{state_data}\n")
                    maybe_rotate_state_file(state_file)
                except OSError as e:
                    sys.stderr.write(f"[statusline] warning: failed to write state file: {e}\n")

    # Session cost (cumulative USD) if enabled — shown even at $0.00 so the
    # segment doesn't flicker in and out across the first few turns.
    if show_cost:
        cost_info = f" | {c_cost}${cost_usd:.2f}{RESET}"

    # Display session_id if enabled
    if show_session and session_id:
        session_info = f" | {c_session}{session_id}{RESET}"

    # Output: dir | branch [changes] | XXk free (XX%) | zone | MI | tok/s | +delta | $cost | [Model] [id]
    # Model name is lowest priority — truncated first when terminal is narrow
    base = f"{c_project_name}{dir_name}{RESET}"
    thinking_text = _format_thinking_info(thinking_budget)
    if thinking_text:
        model_info = f" | {c_model}{model} · {thinking_text}{RESET}"
    else:
        model_info = f" | {c_model}{model}{RESET}"
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
