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

  show_pr=true   (show associated PR number like #42, requires gh CLI - default)
  show_pr=false  (hide PR number)

When AC is enabled, 22.5% of context window is reserved for autocompact buffer.

State file format (CSV):
  timestamp,total_input_tokens,total_output_tokens,current_usage_input_tokens,
  current_usage_output_tokens,current_usage_cache_creation,current_usage_cache_read,
  total_cost_usd,total_lines_added,total_lines_removed,session_id,model_id,
  workspace_project_dir,context_window_size,total_api_duration_ms
"""

import json
import os
import shutil
import subprocess
import sys
import time
import traceback

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None  # type: ignore[assignment]


def _load_shared_module():
    """Locate the single-sourced shared logic module for this script.

    Resolution order (Task 5.2, F-DEAD-001):

    1. The installed package (``claude_statusline._shared``) — repo checkouts
       and pip installs.
    2. The vendored copy shipped beside this script
       (``scripts/_statusline_shared.py``) — byte-identical to the package
       module; equality is enforced by ``tests/python/test_parity.py``.
    3. A repository ``src/`` checkout found next to the script's parent
       directory, bootstrapped onto ``sys.path``.

    Exits with guidance when none is available (an incomplete deployment).
    """
    try:
        from claude_statusline import _shared

        return _shared
    except ImportError:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    vendored = os.path.join(here, "_statusline_shared.py")
    if os.path.exists(vendored):
        import importlib.util

        spec = importlib.util.spec_from_file_location("_statusline_shared", vendored)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            sys.modules["_statusline_shared"] = module
            spec.loader.exec_module(module)
            return module

    src_root = os.path.join(os.path.dirname(here), "src")
    if os.path.isdir(src_root):
        sys.path.insert(0, src_root)
        try:
            from claude_statusline import _shared

            return _shared
        except ImportError:
            pass

    sys.stderr.write(
        "[statusline] error: cannot locate the shared statusline module "
        "(install context-stats, or ship scripts/_statusline_shared.py "
        "alongside this script).\n"
    )
    raise SystemExit(1)


_shared = _load_shared_module()

# ---------------------------------------------------------------------------
# Single-sourced constants (canonical home: claude_statusline/_shared.py)
# ---------------------------------------------------------------------------

ROTATION_THRESHOLD = _shared.ROTATION_THRESHOLD
ROTATION_KEEP = _shared.ROTATION_KEEP

MI_GREEN_THRESHOLD = _shared.MI_GREEN_THRESHOLD
MI_YELLOW_THRESHOLD = _shared.MI_YELLOW_THRESHOLD
MI_CONTEXT_YELLOW = _shared.MI_CONTEXT_YELLOW_THRESHOLD
MI_CONTEXT_RED = _shared.MI_CONTEXT_RED_THRESHOLD

MODEL_PROFILES = _shared.MODEL_PROFILES

LARGE_MODEL_THRESHOLD = _shared.LARGE_MODEL_THRESHOLD
ZONE_1M_P_MAX = _shared.ZONE_1M_P_MAX
ZONE_1M_C_MAX = _shared.ZONE_1M_C_MAX
ZONE_1M_D_MAX = _shared.ZONE_1M_D_MAX
ZONE_1M_X_MAX = _shared.ZONE_1M_X_MAX
ZONE_STD_DUMP_ZONE = _shared.ZONE_STD_DUMP_ZONE
ZONE_STD_WARN_BUFFER = _shared.ZONE_STD_WARN_BUFFER
ZONE_STD_HARD_LIMIT = _shared.ZONE_STD_HARD_LIMIT
ZONE_STD_DEAD_ZONE = _shared.ZONE_STD_DEAD_ZONE

_ZONE_RECOMMENDATIONS = _shared._ZONE_RECOMMENDATIONS

COMPACTION_DROP_THRESHOLD = _shared.COMPACTION_DROP_THRESHOLD
COMPACT_MI_WARN_THRESHOLD = _shared.COMPACT_MI_WARN_THRESHOLD

PACMAN_ICONS = _shared.PACMAN_ICONS

# ANSI Colors (defaults, overridable via config — GREEN/YELLOW/RED are
# reassigned by _render from config color overrides)
BLUE = _shared.BLUE
MAGENTA = _shared.MAGENTA
CYAN = _shared.CYAN
GREEN = _shared.GREEN
YELLOW = _shared.YELLOW
RED = _shared.RED
DIM = _shared.DIM
RESET = _shared.RESET

# Named colors for config parsing
_COLOR_NAMES = _shared.COLOR_NAMES

# Color config keys and which color slot they map to
_COLOR_KEYS = _shared._COLOR_KEYS

# Zone threshold config keys (integer token counts)
_ZONE_INT_KEYS = _shared._ZONE_INT_KEYS

# Zone threshold config keys (float ratios 0-1)
_ZONE_FLOAT_KEYS = _shared._ZONE_FLOAT_KEYS

# Compaction-related float config keys (fractions in (0, 1))
_COMPACTION_FLOAT_KEYS = _shared._COMPACTION_FLOAT_KEYS

# Pattern to strip ANSI escape sequences
_ANSI_RE = _shared._ANSI_RE

_PART_SEPARATOR = _shared._PART_SEPARATOR

_PR_CACHE_TTL_SECONDS = _shared._PR_CACHE_TTL_SECONDS
_PR_CACHE_NEGATIVE_TTL_SECONDS = _shared._PR_CACHE_NEGATIVE_TTL_SECONDS

# ---------------------------------------------------------------------------
# Single-sourced functions (bodies live only in _shared / the vendored copy)
# ---------------------------------------------------------------------------

_parse_color = _shared.parse_color
get_model_profile = _shared.get_model_profile
compute_mi = _shared.compute_mi
compute_tps = _shared.compute_tps
format_tps = _shared.format_tps
detect_compaction_events = _shared.detect_compaction_events
visible_width = _shared.visible_width
get_terminal_width = _shared.get_terminal_width
fit_to_width = _shared.fit_to_width
_ensure_utf8_stdout = _shared._ensure_utf8_stdout
_extract = _shared._extract
_resolve_project_dir = _shared._resolve_project_dir
_format_thinking_info = _shared._format_thinking_info
_tps_tail_size = _shared._tps_tail_size
_TPS_TAIL_BUFFER = _shared._TPS_TAIL_BUFFER
_validate_session_id = _shared._validate_session_id
_validate_csv_field = _shared._validate_csv_field
_csv_unsafe_reason = _shared._csv_unsafe_reason
_sanitize_workspace_dir = _shared._sanitize_workspace_dir
parse_state_row = _shared.parse_state_row
_lock_state_file = _shared._lock_state_file
_unlock_state_file = _shared._unlock_state_file
_rotate_lines = _shared.rotate_lines
get_pacman_icon = _shared.get_pacman_icon
get_git_info = _shared.git_info
_pr_cache_file = _shared._pr_cache_file
_pr_cache_get = _shared._pr_cache_get
_pr_cache_set = _shared._pr_cache_set


def _mi_color_ansi(mi, utilization=0.0):
    """ANSI color for an MI score, honoring config overrides of the script palette."""
    return {"red": RED, "yellow": YELLOW, "green": GREEN}[_shared.mi_color_name(mi, utilization)]


# Parity row "MI colors": same tier decision as graphs/intelligence.get_mi_color,
# rendered through this script's overridable palette globals.
get_mi_color = _mi_color_ansi


def _zone_ansi_color(color_name):
    """Map zone color name to ANSI escape code using the script palette."""
    return _shared.zone_ansi_code(color_name, green=GREEN, yellow=YELLOW, reset=RESET)


def _context_zone_from_config(used_tokens, context_window_size, zone_config=None):
    """Determine context zone indicator based on token usage.

    Returns (zone_word, color_name, recommendation) tuple.
    zone_config is an optional dict of threshold overrides (0 = use default).
    """
    zc = zone_config or {}
    return _shared.context_zone_tuple(
        used_tokens,
        context_window_size,
        large_model_threshold=zc.get("large_model_threshold") or 0,
        zone_1m_plan_max=zc.get("zone_1m_plan_max") or 0,
        zone_1m_code_max=zc.get("zone_1m_code_max") or 0,
        zone_1m_dump_max=zc.get("zone_1m_dump_max") or 0,
        zone_1m_xdump_max=zc.get("zone_1m_xdump_max") or 0,
        zone_std_dump_ratio=zc.get("zone_std_dump_ratio") or 0.0,
        zone_std_warn_buffer=zc.get("zone_std_warn_buffer") or 0,
        zone_std_hard_limit=zc.get("zone_std_hard_limit") or 0.0,
        zone_std_dead_ratio=zc.get("zone_std_dead_ratio") or 0.0,
    )


# Parity row "Zone indicator": tuple-returning adapter over the shared core.
get_context_zone = _context_zone_from_config


def _rotate_state_file_locked(state_file, fh):
    """Rotation core — caller must hold the exclusive lock on ``fh``.

    Keeps the most recent ROTATION_KEEP lines via atomic temp-file + rename.
    Parity: mirrors ``claude_statusline.core.state.StateFile._rotate_locked``.
    """
    try:
        fh.seek(0)
        lines = fh.readlines()
        if len(lines) <= ROTATION_THRESHOLD:
            return
        _rotate_lines(state_file, lines, keep=ROTATION_KEEP)
    except OSError as e:
        sys.stderr.write(f"[statusline] warning: failed to rotate state file: {e}\n")


def maybe_rotate_state_file(state_file):
    """Rotate a state file if it exceeds ROTATION_THRESHOLD lines.

    Standalone entry point: reads the line count under a best-effort lock,
    then closes the handle BEFORE the atomic rename. Windows cannot
    ``os.replace`` a path another handle holds open, so keeping the
    descriptor across the rename would silently skip rotation there.
    Parity: mirrors ``claude_statusline.core.state.StateFile._maybe_rotate``.
    """
    try:
        if not os.path.exists(state_file):
            return
        with open(state_file) as f:
            _lock_state_file(f)
            try:
                f.seek(0)
                lines = f.readlines()
            finally:
                _unlock_state_file(f)
        if len(lines) <= ROTATION_THRESHOLD:
            return
        _rotate_lines(state_file, lines, keep=ROTATION_KEEP)
    except OSError as e:
        sys.stderr.write(f"[statusline] warning: failed to rotate state file: {e}\n")


def _migrate_legacy_state_files(state_dir, old_state_dir):
    """Migrate legacy state files from ``old_state_dir`` into ``state_dir``.

    Migration must never break the refresh that triggered it (F-BUG-005):
    every move/remove is guarded, warning on failure and leaving the file
    for a later pass. Parity: mirrors
    ``claude_statusline.core.state.StateFile._migrate_old_files``.
    """
    import glob

    for old_file in glob.glob(os.path.join(old_state_dir, "statusline*.state")):
        if os.path.isfile(old_file):
            new_file = os.path.join(state_dir, os.path.basename(old_file))
            try:
                if not os.path.exists(new_file):
                    shutil.move(old_file, new_file)
                else:
                    os.remove(old_file)
            except OSError as e:
                sys.stderr.write(
                    f"[statusline] warning: failed to migrate legacy state file {old_file}: {e}\n"
                )


# Config keys parsed as booleans ("false" — case-insensitive — means off).
_BOOL_CONFIG_KEYS = frozenset(
    {
        "autocompact",
        "token_detail",
        "show_delta",
        "show_session",
        "show_io_tokens",
        "reduced_motion",
        "show_mi",
        "show_tps",
        "show_pr",
        "show_cost",
        "show_effort",
        "show_pacman",
    }
)

# Config keys parsed as integers with a per-key inclusive minimum.
_MIN_INT_CONFIG_KEYS = {"tps_precision": 0, "tps_window": 1}

# Config keys parsed as floats constrained to the open interval (0, 1).
_RANGE01_CONFIG_KEYS = frozenset(_ZONE_FLOAT_KEYS | _COMPACTION_FLOAT_KEYS)


def _apply_config_value(config, key, raw_value):
    """Apply one ``key=value`` config pair via the parser dispatch tables.

    Mirrors ``claude_statusline.core.config.Config._read_config`` branch by
    branch: identical accepted ranges, defaults, and stderr warnings.
    """
    if key in _BOOL_CONFIG_KEYS:
        config[key] = raw_value.lower() != "false"
    elif key == "mi_curve_beta":
        try:
            config["mi_curve_beta"] = float(raw_value)
        except ValueError:
            pass
    elif key in _MIN_INT_CONFIG_KEYS:
        minimum = _MIN_INT_CONFIG_KEYS[key]
        try:
            v = int(raw_value)
        except ValueError:
            sys.stderr.write(f"[statusline] warning: invalid integer for {key}: '{raw_value}'\n")
            return
        if v >= minimum:
            config[key] = v
        else:
            sys.stderr.write(
                f"[statusline] warning: {key} must be >= {minimum}, ignoring '{raw_value}'\n"
            )
    elif key == "tps_unit":
        if raw_value:
            config["tps_unit"] = raw_value
    elif key in _ZONE_INT_KEYS:
        try:
            v = int(raw_value)
        except ValueError:
            sys.stderr.write(f"[statusline] warning: invalid integer for {key}: '{raw_value}'\n")
            return
        if v > 0:
            config["zone_config"][key] = v
        else:
            sys.stderr.write(
                f"[statusline] warning: {key} must be positive, ignoring '{raw_value}'\n"
            )
    elif key in _RANGE01_CONFIG_KEYS:
        target = config["zone_config"] if key in _ZONE_FLOAT_KEYS else config
        try:
            v = float(raw_value)
        except ValueError:
            sys.stderr.write(f"[statusline] warning: invalid number for {key}: '{raw_value}'\n")
            return
        if 0.0 < v < 1.0:
            target[key] = v
        else:
            sys.stderr.write(
                f"[statusline] warning: {key} must be between 0 and 1, ignoring '{raw_value}'\n"
            )
    elif key in _COLOR_KEYS:
        ansi = _parse_color(raw_value)
        if ansi:
            config["colors"][_COLOR_KEYS[key]] = ansi


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
        "show_pr": True,
        "show_cost": True,
        "show_effort": True,
        "show_pacman": True,
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
                f.write(_DEFAULT_CONF_TEMPLATE)
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
                _apply_config_value(config, key.strip(), value.strip())
    except (OSError, UnicodeDecodeError) as e:
        sys.stderr.write(f"[statusline] warning: failed to read config: {e}\n")
    return config

# Default config template written when ~/.claude/statusline.conf does not
# exist yet. Hoisted to a module constant (Task 5.3, F-CLEAN-003) so
# read_config() stays focused on parsing.
_DEFAULT_CONF_TEMPLATE = """\
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
#   false = PR number hidden
#   true  = PR number visible (e.g., #42) (default)
show_pr=true

# Show the cumulative session cost in USD (e.g., $0.42).
# Cost is reported by Claude Code (cost.total_cost_usd); the value is the
# running total for the whole session, shown even at $0.00.
#   true  = cost visible (default)
#   false = cost hidden
show_cost=true


# Show the current reasoning effort level next to the model name (e.g.,
# "Opus 4.8·high"). Claude Code reports effort.level as one of
# low/medium/high/xhigh/max; the segment hides when no effort is reported.
#   true  = effort visible (default)
#   false = effort hidden
show_effort=true

# Show a pacman-style icon reflecting the current context zone (Plan/Code/
# Dump/ExDump/Dead) next to the zone label — a quick emotional cue for how
# much context headroom remains, beyond the numeric/graph indicators.
#   true  = icon visible (default)
#   false = icon hidden
show_pacman=true


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
#   project_name | branch [changes] | tokens_free (%)·Zone·pacman | MI:score | tok/s | +delta | Model·effort | session_id
#
# Example output:
#   my-project | main [3] | 64,000 free (32.0%)·Code·ᗤ | MI:0.918 | 42.5 tok/s | +2,500 | Opus 4.6·high | abc-123
#
# If the terminal is too narrow to fit everything on one line, the line
# wraps onto additional lines instead of dropping elements — nothing is
# lost. Priority controls which elements wrap to a later line first
# (lowest priority wraps first); the base always starts line 1:
#   1. session_id    (wraps to a new line first)
#   2. model name
#   3. token delta
#   4. tok/s throughput
#   5. MI score
#   6. zone indicator
#   7. context info
#   8. git info
#   9. project name  (base — always starts the first line)
"""

def get_pr_number(project_dir: str) -> str:
    """Look up the PR number for the current branch via gh CLI.

    Returns a formatted string like ``#42`` when an open PR exists,
    or an empty string when no PR is associated or gh CLI is unavailable.
    """
    if shutil.which("gh") is None:
        return ""

    cache_key = None
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

        cache_key = f"{project_dir}\t{branch_name}"
        cached = _pr_cache_get(cache_key, cache_file=_pr_cache_file())
        if cached is not None:
            return str(cached)

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
            # Negatively cache the failure (short TTL) so a broken gh
            # environment does not stall every render on a live lookup.
            _pr_cache_set(cache_key, "", ttl=_PR_CACHE_NEGATIVE_TTL_SECONDS, cache_file=_pr_cache_file())
            return ""

        try:
            data = json.loads(result.stdout.strip())
        except (json.JSONDecodeError, ValueError):
            _pr_cache_set(cache_key, "", ttl=_PR_CACHE_NEGATIVE_TTL_SECONDS, cache_file=_pr_cache_file())
            return ""

        pr_str = ""
        if data and len(data) > 0:
            pr_num = data[0].get("number", "")
            if pr_num:
                pr_str = f"#{pr_num}"
        _pr_cache_set(cache_key, pr_str, cache_file=_pr_cache_file())
        return pr_str
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        if cache_key is not None:
            _pr_cache_set(cache_key, "", ttl=_PR_CACHE_NEGATIVE_TTL_SECONDS, cache_file=_pr_cache_file())
        return ""

def main():
    _ensure_utf8_stdout()

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.stdout.write("[Claude] ~\n")
        return

    # Render catch-all (F-BUG-004): any unexpected exception degrades to a
    # minimal status line on stdout with diagnostics on stderr only — never a
    # raw traceback as the status line.
    try:
        _render(data)
    except Exception:  # noqa: BLE001 - deliberate catch-all render boundary
        sys.stderr.write("[statusline] warning: rendering failed; fallback line emitted\n")
        sys.stderr.write(traceback.format_exc())
        sys.stdout.write("[Claude] ~\n")


def _render(data):
    """Render the status line for an already-parsed stdin payload."""
    # Extract data — every lookup treats explicit JSON null like an absent key
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
    show_effort = config["show_effort"]
    show_pacman = config["show_pacman"]
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

    # Git info (use per-property branch color, fallback to green). Gated on
    # the resolved project dir — see _resolve_project_dir (F-SEC-002).
    safe_project_dir = _resolve_project_dir(project_dir)
    git_info = ""
    if safe_project_dir:
        git_info = get_git_info(safe_project_dir, magenta=c_branch_name, cyan=c_cyan)

    session_id = _extract(data, "session_id")
    if session_id is not None:
        # Path-traversal defense (F-BUG-002): a session_id carrying '/', '\',
        # '..' or null bytes must never reach state-file path construction.
        try:
            _validate_session_id(session_id)
        except ValueError as e:
            sys.stderr.write(f"[statusline] warning: {e}\n")
            session_id = None

    # Context window calculation
    context_info = ""
    delta_info = ""
    mi_info = ""
    tps_info = ""
    cost_info = ""
    zone_info = ""
    pacman_info = ""
    session_info = ""
    pr_info = ""

    # PR number lookup
    if show_pr and safe_project_dir:
        pr_num = get_pr_number(safe_project_dir)
        if pr_num:
            pr_info = f" | {c_separator}{pr_num}{RESET}"
    context_data = _extract(data, "context_window", {})
    total_size = _extract(context_data, "context_window_size", 0)
    current_usage = _extract(context_data, "current_usage")
    total_input_tokens = _extract(context_data, "total_input_tokens", 0)
    total_output_tokens = _extract(context_data, "total_output_tokens", 0)
    cost_data = _extract(data, "cost", {})
    cost_usd = _extract(cost_data, "total_cost_usd", 0) or 0
    lines_added = _extract(cost_data, "total_lines_added", 0)
    lines_removed = _extract(cost_data, "total_lines_removed", 0)
    api_duration_ms = _extract(cost_data, "total_api_duration_ms", 0)
    model_id = _extract(model_data, "id", "")
    workspace_project_dir = _extract(workspace_data, "project_dir", "")

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
        zone_info = f"·{effective_zone_color}{zone_word}{RESET}"

        # Pacman-style icon reflecting the same zone — on by default.
        if show_pacman:
            pacman_glyph = get_pacman_icon(zone_word)
            if pacman_glyph:
                pacman_info = f"·{effective_zone_color}{pacman_glyph}{RESET}"

        # Read previous entry if needed for delta, MI, or throughput (tok/s).
        # tok/s needs the previous row (for the API-time delta) and persists
        # the current api_duration for the next refresh, so it widens this gate.
        if show_delta or show_mi or show_tps:
            state_dir = os.path.expanduser("~/.claude/statusline")
            os.makedirs(state_dir, exist_ok=True)

            _migrate_legacy_state_files(state_dir, os.path.expanduser("~/.claude"))

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
                            # Last line drives delta/dedup via parse_state_row
                            # (F-CLEAN-007): one parser serves the last-entry read
                            # and the bounded tail below. A trailing comma-bearing
                            # row that fails to parse degrades to "no previous
                            # usage" (prev_tokens stays 0) instead of killing the
                            # whole tok/s sample collection like the old
                            # index-magic path did on a ValueError.
                            last_line = file_lines[-1].strip()
                            parsed_last = parse_state_row(last_line)
                            if parsed_last is not None:
                                # Previous context usage: cur_input[3] +
                                # cache_creation[5] + cache_read[6].
                                prev_tokens = (
                                    parsed_last["current_input_tokens"]
                                    + parsed_last["cache_creation"]
                                    + parsed_last["cache_read"]
                                )
                            elif "," not in last_line:
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
                                    parsed = parse_state_row(line)
                                    if parsed is None:
                                        continue
                                    tps_samples.append(
                                        (parsed["output_tokens"], parsed["api_duration_ms"])
                                    )
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
                    # CSV-safety defense (F-BUG-006): string fields are
                    # validated before joining so a comma/newline/control
                    # character can never shift the 15-field column indexes.
                    _validate_csv_field("session_id", session_id or "")
                    _validate_csv_field("model_id", model_id)
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
                            _sanitize_workspace_dir(workspace_project_dir),
                            total_size,
                            api_duration_ms,
                        ]
                    )
                except ValueError as e:
                    sys.stderr.write(f"[statusline] warning: refusing to write state file: {e}\n")
                else:
                    try:
                        # Create with owner-only permissions (F-SEC-003): state
                        # rows carry session ids and costs. The append and the
                        # subsequent rotation share one exclusive advisory lock
                        # (F-BUG-008) so rotation cannot drop a concurrently
                        # appended line.
                        fd = os.open(state_file, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
                        with os.fdopen(fd, "a+") as f:
                            _lock_state_file(f)
                            try:
                                f.write(f"{state_data}\n")
                                f.flush()
                                if fcntl is not None:
                                    # POSIX only: the rename may run while this
                                    # descriptor still holds the file open.
                                    # Windows cannot replace an open file, so
                                    # it falls back after the close below.
                                    _rotate_state_file_locked(state_file, f)
                            finally:
                                _unlock_state_file(f)
                    except OSError as e:
                        sys.stderr.write(f"[statusline] warning: failed to write state file: {e}\n")
                    else:
                        if fcntl is None:
                            maybe_rotate_state_file(state_file)

    # Session cost (cumulative USD) if enabled — shown even at $0.00 so the
    # segment doesn't flicker in and out across the first few turns.
    if show_cost:
        cost_info = f" | {c_cost}${cost_usd:.2f}{RESET}"

    # Display session_id if enabled
    if show_session and session_id:
        session_info = f" | {c_session}{session_id}{RESET}"

    # Output: dir | branch [changes] | XXk free (XX%)·zone·pacman | MI | tok/s | +delta | $cost | [Model] [id]
    # Model name is lowest priority — wraps to a new line first when narrow
    base = f"{c_project_name}{dir_name}{RESET}"
    thinking_text = _format_thinking_info(thinking_budget)
    # Build the model suffix from any present indicators (thinking budget,
    # reasoning effort). Effort hides gracefully when absent/null/disabled.
    model_suffix = ""
    if thinking_text:
        model_suffix += f"·{thinking_text}"
    if show_effort and effort_level:
        model_suffix += f"·{effort_level}"
    model_info = f" | {c_model}{model}{model_suffix}{RESET}"
    max_width = get_terminal_width()
    parts = [
        base,
        git_info,
        pr_info,
        # Context group: tokens·zone·pacman. Joined with "·" (no spaces) and
        # kept as ONE atomic part so the group never splits across lines on a
        # narrow terminal — fit_to_width() only strips a leading " | ", so a
        # "·"-prefixed part starting a wrapped line would show a stray "·".
        context_info + zone_info + pacman_info,
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
