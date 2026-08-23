"""Single-sourced statusline primitives shared by both implementations.

Task 5.2 (#143): every symbol in this module is pure or stdlib-only statusline
logic consumed by BOTH the installable package and the standalone script
(``scripts/statusline.py``), eliminating the duplicated bodies tracked as
F-DEAD-001. The behavioral contract for every pair remains the Sync Points
table in CLAUDE.md, guarded by ``tests/python/test_parity.py``.

The standalone script imports this module through its loader: first as part of
the installed package, then from the byte-identical vendored copy shipped next
to it (``scripts/_statusline_shared.py``, kept in lockstep by a parity test),
and finally by bootstrapping a repository ``src/`` checkout onto ``sys.path``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# State rotation (append-only CSV contract, docs/CSV_FORMAT.md)
ROTATION_THRESHOLD = 10_000
ROTATION_KEEP = 5_000

# Model Intelligence color thresholds — based on MI value and context utilization
MI_GREEN_THRESHOLD = 0.90
MI_YELLOW_THRESHOLD = 0.80
MI_CONTEXT_YELLOW_THRESHOLD = 0.40  # 40% context used
MI_CONTEXT_RED_THRESHOLD = 0.80  # 80% context used

# Per-model degradation profiles calibrated from MRCR v2 8-needle benchmark
# beta controls curve shape: higher = quality retained longer
MODEL_PROFILES: dict[str, float] = {
    "opus": 1.8,
    "sonnet": 1.5,
    "haiku": 1.2,
    "default": 1.5,
}

# Zone indicator thresholds
LARGE_MODEL_THRESHOLD = 500_000  # >= 500k context = 1M-class model
# Recalibrated from observed context rot onset at 300-400k tokens.
# Source: x.com/trq212/status/2044548257058328723
ZONE_1M_P_MAX = 150_000  # P zone: < 150k used
ZONE_1M_C_MAX = 250_000  # C zone: 150k–250k used
ZONE_1M_D_MAX = 400_000  # D zone: 250k–400k used
ZONE_1M_X_MAX = 450_000  # X zone: 400k–450k used; Z zone: >= 450k
ZONE_STD_DUMP_ZONE = 0.40
ZONE_STD_WARN_BUFFER = 30_000
ZONE_STD_HARD_LIMIT = 0.70
ZONE_STD_DEAD_ZONE = 0.75

# Zone recommendation strings — one-line action guidance per zone
_ZONE_RECOMMENDATIONS: dict[str, str] = {
    "Plan": "Safe to plan and code",
    "Code": "Avoid starting new tasks; finish current one",
    "Dump": "Consider `/compact focus on X` or delegate to subagent",
    "ExDump": "Run `/compact` now before quality degrades further",
    "Dead": "Start a new session with `/clear`",
}

# Pacman-style icon per zone — single-codepoint, width-1 glyphs (Canadian
# Aboriginal Syllabics) so they render predictably in any terminal and are
# counted correctly by visible_width()'s plain len().
PACMAN_ICONS: dict[str, str] = {
    "Plan": "ᗧ",
    "Code": "ᗤ",
    "Dump": "ᗣ",
    "ExDump": "ᗢ",
    "Dead": "×",
}

# Compaction detection defaults
COMPACTION_DROP_THRESHOLD = 0.5
COMPACT_MI_WARN_THRESHOLD = 0.6

# Autocompact reserve (F-CLEAN-010): when autocompact is enabled, this
# fraction of the context window is reserved as the buffer (45k of a
# 200k window) before "free" tokens are reported.
AUTOCOMPACT_RATIO = 0.225

# Extra rows read beyond ``tps_window`` when tail-reading state history for
# tok/s. compute_tps needs the last ``tps_window`` valid *turns* (=
# ``tps_window + 1`` valid rows); this headroom absorbs sparse dropped rows
# plus any legacy/blank rows so the rendered value matches a full-history
# read while each refresh parses only a bounded tail.
_TPS_TAIL_BUFFER = 8

# ANSI color codes (defaults)
BLUE = "\033[0;34m"
MAGENTA = "\033[0;35m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# Named colors for config parsing
COLOR_NAMES: dict[str, str] = {
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

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")

# Color config keys and which color slot they map to
_COLOR_KEYS: dict[str, str] = {
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
_ZONE_INT_KEYS: set[str] = {
    "zone_1m_plan_max",
    "zone_1m_code_max",
    "zone_1m_dump_max",
    "zone_1m_xdump_max",
    "zone_std_warn_buffer",
    "large_model_threshold",
}

# Zone threshold config keys (float ratios 0-1)
_ZONE_FLOAT_KEYS: set[str] = {
    "zone_std_dump_ratio",
    "zone_std_hard_limit",
    "zone_std_dead_ratio",
}

# Compaction-related float config keys (fractions in (0, 1))
_COMPACTION_FLOAT_KEYS: set[str] = {
    "compaction_drop_threshold",
    "compact_mi_warn_threshold",
}

# Pattern to strip ANSI escape sequences
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# Separator that prefixes every part except the base during width reflow.
_PART_SEPARATOR = " | "

# PR-number lookups shell out to ``gh`` (a network call). Because the
# statusline re-renders frequently, the result is cached per-branch for a
# short TTL so the network round-trip happens at most once per window.
_PR_CACHE_TTL_SECONDS = 60
# Failed lookups (gh errors, timeouts) get a much shorter TTL so a broken
# environment recovers quickly instead of stalling every render for a full
# positive-TTL window.
_PR_CACHE_NEGATIVE_TTL_SECONDS = 10


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

# Fixed RGB ANSI codes for the traffic-light zone tiers beyond green/yellow
# (F-CLEAN-010): orange (Dump), dark red (ExDump), and gray (Dead) are true-color
# literals on both implementations, so they are named once here.
ZONE_ORANGE_ANSI = "\033[38;2;255;165;0m"  # RGB orange
ZONE_DARK_RED_ANSI = "\033[38;2;139;0;0m"  # RGB dark red
ZONE_GRAY_ANSI = "\033[0;90m"  # bright black / gray

# Thinking-budget display tiers (F-CLEAN-010): budgets below THINKING_K_FLOOR
# are shown exactly; budgets from the floor up to THINKING_K_ROUND_MIN are
# floored to whole "Nk"; up to THINKING_M_THRESHOLD they round to "Nk"; and at
# or above the threshold they render as "NM".
THINKING_K_FLOOR = 5_000
THINKING_K_ROUND_MIN = 10_000
THINKING_M_THRESHOLD = 1_000_000


def parse_color(value: str) -> str | None:
    """Parse a color name or #rrggbb hex into an ANSI escape code.

    Returns None when the value is not recognized.
    """
    value = value.strip().lower()
    if not value:
        return None
    if value in COLOR_NAMES:
        return COLOR_NAMES[value]
    m = _HEX_RE.match(value)
    if m:
        hex_str = m.group(1)
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"
    return None


def zone_ansi_code(
    color_name: str, green: str = GREEN, yellow: str = YELLOW, reset: str = RESET
) -> str:
    """Map a zone color name to an ANSI escape code.

    ``green``/``yellow``/``reset`` are injected by the caller so config
    overrides applied to the caller's palette are honored; the
    orange/dark-red/gray codes are the fixed RGB literals named above.
    """
    if color_name == "green":
        return green
    if color_name == "yellow":
        return yellow
    if color_name == "orange":
        return ZONE_ORANGE_ANSI
    if color_name == "dark_red":
        return ZONE_DARK_RED_ANSI
    if color_name == "gray":
        return ZONE_GRAY_ANSI
    return reset


def mi_color_name(mi: float, utilization: float = 0.0) -> str:
    """Return the traffic-light tier name ("red"/"yellow"/"green") for an MI score.

    Considers both the MI value and the context utilization.
    """
    if mi <= MI_YELLOW_THRESHOLD or utilization >= MI_CONTEXT_RED_THRESHOLD:
        return "red"
    if mi < MI_GREEN_THRESHOLD or utilization >= MI_CONTEXT_YELLOW_THRESHOLD:
        return "yellow"
    return "green"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def visible_width(s: str) -> int:
    """Return the visible width of a string after stripping ANSI escape sequences."""
    return len(_ANSI_RE.sub("", s))


def get_terminal_width() -> int:
    """Return the terminal width in columns.

    Claude Code captures the statusline script's output rather than
    connecting it to a TTY, so ``shutil.get_terminal_size()`` cannot read
    the real width and falls back to 80. Since Claude Code v2.1.153, the
    harness exports ``COLUMNS`` (and ``LINES``) with the real terminal
    dimensions before running the script, so we trust ``COLUMNS`` when it
    is set. When it is absent we use a generous default of 200 so the
    single line is not wrapped or truncated on a fallback artifact.
    """
    if os.environ.get("COLUMNS"):
        return shutil.get_terminal_size().columns
    cols = shutil.get_terminal_size(fallback=(200, 24)).columns
    return 200 if cols == 80 else cols


def fit_to_width(parts: list[str], max_width: int) -> str:
    """Assemble parts into lines that each fit within max_width.

    Parts are packed greedily in priority order (first = highest priority).
    The first part (base) always starts the first line. Each subsequent
    part is appended to the current line when it fits; otherwise it starts
    a new line so no information is dropped on narrow terminals. A leading
    separator is stripped from wrapped lines so they do not begin with a
    dangling " | ".
    """
    if not parts:
        return ""

    lines: list[str] = []
    current = parts[0]
    current_width = visible_width(current)

    for part in parts[1:]:
        if not part:
            continue
        part_width = visible_width(part)
        if current_width + part_width <= max_width:
            current += part
            current_width += part_width
        else:
            lines.append(current)
            if part.startswith(_PART_SEPARATOR):
                part = part[len(_PART_SEPARATOR) :]
            current = part
            current_width = visible_width(part)

    lines.append(current)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Model Intelligence / zones / pacman
# ---------------------------------------------------------------------------


def get_model_profile(model_id: str) -> float:
    """Match model_id to degradation beta."""
    model_lower = (model_id or "").lower()
    for family in ("opus", "sonnet", "haiku"):
        if family in model_lower:
            return MODEL_PROFILES[family]
    return MODEL_PROFILES["default"]


def calculate_context_pressure(utilization: float, beta: float = 1.5) -> float:
    """Calculate Model Intelligence from context utilization: max(0, 1 - u^beta)."""
    if utilization <= 0:
        return 1.0
    return max(0.0, 1.0 - utilization**beta)  # type: ignore[no-any-return]


def compute_mi(used_tokens, context_window_size, model_id="", beta_override=0.0):
    """Compute the Model Intelligence score for a raw token reading.

    MI(u) = max(0, 1 - u^beta) where beta comes from the model profile unless
    a positive override is given. Returns 1.0 for a zero-sized window.
    """
    if context_window_size == 0:
        return 1.0
    beta_from_profile = get_model_profile(model_id)
    beta = beta_override if beta_override > 0 else beta_from_profile
    u = used_tokens / context_window_size
    return calculate_context_pressure(u, beta)


def get_pacman_icon(zone: str) -> str:
    """Get the pacman-style icon for a context zone ("" when unrecognized)."""
    return PACMAN_ICONS.get(zone, "")


def context_zone_tuple(
    used_tokens: int,
    context_window_size: int,
    *,
    zone_1m_plan_max: int = 0,
    zone_1m_code_max: int = 0,
    zone_1m_dump_max: int = 0,
    zone_1m_xdump_max: int = 0,
    zone_std_dump_ratio: float = 0.0,
    zone_std_warn_buffer: int = 0,
    zone_std_hard_limit: float = 0.0,
    zone_std_dead_ratio: float = 0.0,
    large_model_threshold: int = 0,
) -> tuple[str, str, str]:
    """Determine the context zone indicator: (zone_word, color_name, recommendation).

    A threshold override of 0 (or 0.0) means "use the module-level default".
    """
    if context_window_size == 0:
        return ("Plan", "green", _ZONE_RECOMMENDATIONS["Plan"])

    lmt = large_model_threshold or LARGE_MODEL_THRESHOLD
    is_large = context_window_size >= lmt

    if is_large:
        p_max = zone_1m_plan_max or ZONE_1M_P_MAX
        c_max = zone_1m_code_max or ZONE_1M_C_MAX
        d_max = zone_1m_dump_max or ZONE_1M_D_MAX
        x_max = zone_1m_xdump_max or ZONE_1M_X_MAX

        if used_tokens < p_max:
            return ("Plan", "green", _ZONE_RECOMMENDATIONS["Plan"])
        if used_tokens < c_max:
            return ("Code", "yellow", _ZONE_RECOMMENDATIONS["Code"])
        if used_tokens < d_max:
            return ("Dump", "orange", _ZONE_RECOMMENDATIONS["Dump"])
        if used_tokens < x_max:
            return ("ExDump", "dark_red", _ZONE_RECOMMENDATIONS["ExDump"])
        return ("Dead", "gray", _ZONE_RECOMMENDATIONS["Dead"])

    dump_ratio = zone_std_dump_ratio or ZONE_STD_DUMP_ZONE
    warn_buf = zone_std_warn_buffer or ZONE_STD_WARN_BUFFER
    hard_lim = zone_std_hard_limit or ZONE_STD_HARD_LIMIT
    dead_rat = zone_std_dead_ratio or ZONE_STD_DEAD_ZONE

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


# ---------------------------------------------------------------------------
# tok/s throughput and compaction detection
# ---------------------------------------------------------------------------


def _tps_tail_size(tps_window: int) -> int:
    """Number of trailing state rows to read for the tok/s rolling average.

    ``tps_window`` valid turns need ``tps_window + 1`` valid rows; doubling the
    window plus a fixed buffer leaves ample room for interleaved dropped rows
    while staying bounded (independent of total file size).
    """
    return max(1, tps_window) * 2 + _TPS_TAIL_BUFFER


def compute_tps(samples, window=5):
    """Compute a smoothed, session-rolling model throughput in tokens/second.

    Each sample is an (output_tokens, cumulative_api_duration_ms) pair. A
    *turn* is the transition between two consecutive samples; turns with a
    non-positive API-time delta or non-positive output are dropped. Returns
    the token-weighted average over the last ``window`` valid turns, or None
    when no valid turn exists yet (None means "hide").
    """
    if window < 1:
        window = 1
    turns = []
    for i in range(1, len(samples)):
        prev_dur = samples[i - 1][1]
        out, cur_dur = samples[i]
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


def detect_compaction_events(values, drop_threshold=None):
    """Detect compaction events: indices where usage dropped by more than
    ``drop_threshold`` fraction in a single step (default 0.5)."""
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


# ---------------------------------------------------------------------------
# Stdin trust boundaries and display glue
# ---------------------------------------------------------------------------


def _ensure_utf8_stdout() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows where cp1252 is the default.

    Guarded with getattr because pytest's CaptureIO (and StringIO stand-ins used
    by tests) do not implement reconfigure().
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        encoding = getattr(stream, "encoding", None)
        if encoding and encoding.lower().replace("-", "") == "utf8":
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - detached/closed stream
            pass


def _extract(data, key, default=None):
    """Read ``key`` from ``data``, treating explicit JSON null as absent.

    External inputs (the stdin payload) may carry explicit nulls where older
    builds sent no key at all; a bare ``dict.get`` chain returns None instead
    of the default for those, which used to crash the render (F-BUG-003).
    Non-dict containers also yield the default.
    """
    if not isinstance(data, dict):
        return default
    value = data.get(key, default)
    return default if value is None else value


def _resolve_project_dir(raw):
    """Resolve a stdin-supplied project_dir to an existing directory, else None.

    Local trust boundary (F-SEC-002): ``workspace.project_dir`` arrives
    verbatim from untrusted stdin JSON. Git/gh subprocesses are only ever run
    with a cwd that has been resolved and verified to exist.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        candidate = os.path.realpath(os.path.expanduser(raw))
    except OSError:
        return None
    return candidate if os.path.isdir(candidate) else None


def _format_thinking_info(budget) -> str:
    """Format thinking budget for display next to model name.

    Returns an empty string when budget is None or zero. Small budgets
    (< THINKING_K_FLOOR) are shown exactly; medium budgets round to "Nk"
    only when reasonable (>= the floor); large budgets (>=
    THINKING_M_THRESHOLD) are shown as "NM".
    """
    if budget is None or budget == 0:
        return ""
    try:
        tokens = int(budget)
    except (ValueError, TypeError):
        return ""
    if tokens <= 0:
        return ""
    if tokens >= THINKING_M_THRESHOLD:
        return f"{tokens // THINKING_M_THRESHOLD}M tokens thinking"
    if tokens >= THINKING_K_ROUND_MIN:
        k = round(tokens / 1_000)
        return f"{k}k tokens thinking"
    if tokens >= THINKING_K_FLOOR:
        return f"{tokens // 1_000}k tokens thinking"
    return f"{tokens} tokens thinking"


# ---------------------------------------------------------------------------
# Session ID validation / CSV safety (docs/CSV_FORMAT.md contract)
# ---------------------------------------------------------------------------


def _validate_session_id(session_id) -> None:
    """Validate that a session ID does not contain dangerous path characters.

    Path-traversal defense plus CSV-safety defense (F-BUG-006): a session_id
    carrying a comma, newline, or other control character would corrupt the
    unquoted 15-field CSV rows, so those are rejected too.

    Raises:
        ValueError: If session_id is not a str, contains '/', '\\', '..', or
            null bytes, or is not CSV-safe (comma/newline/control chars).
    """
    if not isinstance(session_id, str):
        raise ValueError(f"Invalid session_id: expected str, got {type(session_id).__name__}.")
    for bad in ("/", "\\", "..", "\0"):
        if bad in session_id:
            raise ValueError(
                f"Invalid session_id: contains '{bad}'. "
                "Session IDs must not contain '/', '\\', '..', null bytes, "
                "commas, newlines, or control characters."
            )
    _validate_csv_field("session_id", session_id)


def _csv_unsafe_reason(value: str) -> str | None:
    """Describe why ``value`` cannot be written into an unquoted CSV field.

    Returns ``None`` when the value is safe.
    """
    for i, ch in enumerate(value):
        if ch == ",":
            return f"comma at position {i}"
        code = ord(ch)
        if code < 0x20 or code == 0x7F:
            return f"control character U+{code:04X} at position {i}"
    return None


def _validate_csv_field(field: str, value) -> None:
    """Validate that a string field is safe to write into a CSV state row.

    Raises:
        ValueError: If value is not a str, or contains commas, newlines, or
            other control characters (F-BUG-006).
    """
    if not isinstance(value, str):
        raise ValueError(f"Invalid {field}: expected str, got {type(value).__name__}.")
    reason = _csv_unsafe_reason(value)
    if reason is not None:
        raise ValueError(
            f"Invalid {field}: contains {reason}. "
            "String fields must not contain commas, newlines, or control "
            "characters (the state CSV has no quoting/escaping)."
        )


def _sanitize_workspace_dir(value) -> str:
    """Sanitize ``workspace_project_dir`` before writing (CSV_FORMAT contract).

    Commas — and, defensively, newlines/other control characters — are
    replaced with underscores. Non-str values yield an empty string.
    """
    if not isinstance(value, str):
        return ""
    return "".join("_" if (ch == "," or ord(ch) < 0x20 or ord(ch) == 0x7F) else ch for ch in value)


# ---------------------------------------------------------------------------
# State-row parsing (Task 5.3, F-CLEAN-007)
# ---------------------------------------------------------------------------


def parse_state_row(row: str) -> dict[str, int] | None:
    """Parse one CSV state row into the fields both statusline read paths need.

    Serves the last-entry read (previous context usage for the delta segment)
    and the bounded-tail read (tok/s rolling samples) instead of hand-rolled
    index magic at each site (F-CLEAN-007). Rows shorter than five fields or
    with non-integer numeric fields yield ``None``; callers skip such rows
    exactly like ``StateFile.read_tail`` skips unparseable entries.

    CSV indices (docs/CSV_FORMAT.md): cur_in[3], out[4], cache_create[5],
    cache_read[6], api_duration[14]. Legacy rows lacking index 14 report an
    api_duration_ms of 0, which compute_tps treats as "no prior reading".
    """
    parts = row.strip().split(",")
    if len(parts) < 5:
        return None
    try:
        return {
            "current_input_tokens": int(parts[3]),
            "output_tokens": int(parts[4]),
            "cache_creation": int(parts[5]) if len(parts) > 5 else 0,
            "cache_read": int(parts[6]) if len(parts) > 6 else 0,
            "api_duration_ms": int(parts[14]) if len(parts) > 14 else 0,
        }
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# State locking / rotation core
# ---------------------------------------------------------------------------


def _lock_state_file(fh) -> None:
    """Take an exclusive advisory lock on ``fh`` (best-effort, POSIX only).

    Serializes append + rotation between concurrent processes (F-BUG-008).
    """
    if fcntl is None:
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except OSError:
        pass


def _unlock_state_file(fh) -> None:
    """Release the lock taken by :func:`_lock_state_file`."""
    if fcntl is None:
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def rotate_lines(state_file: str, lines: list[str], keep: int = ROTATION_KEEP) -> None:
    """Atomically keep the most recent ``keep`` of ``lines`` via temp-file + rename.

    Raises OSError on failure; callers wrap with their own warnings.
    """
    tail = lines[-keep:]
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(state_file) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as tmp_f:
            tmp_f.writelines(tail)
        os.replace(tmp_path, state_file)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# PR-number cache (shared file format, ~/.claude/statusline/pr_number_cache.json)
# ---------------------------------------------------------------------------


def _pr_cache_file() -> str:
    """Location of the shared PR-number cache file."""
    return os.path.join(os.path.expanduser("~/.claude/statusline"), "pr_number_cache.json")


def _pr_cache_get(key: str, cache_file: str | None = None) -> str | None:
    """Return the cached PR string for ``key`` if present and unexpired.

    ``cache_file`` defaults to :func:`_pr_cache_file`; callers that redirect
    the location at their own module namespace pass it explicitly so runtime
    monkeypatching stays effective.

    Returns ``None`` on any miss (no entry, expired, or read error) so the
    caller falls through to a live lookup. Never raises.
    """
    try:
        with open(cache_file or _pr_cache_file(), encoding="utf-8") as fh:
            cache = json.load(fh)
        if not isinstance(cache, dict):
            return None
        entry = cache.get(key)
        if isinstance(entry, dict) and entry.get("exp", 0) > time.time():
            return str(entry.get("pr", ""))
    except (OSError, ValueError):
        pass
    return None


def _pr_cache_set(key, pr, ttl=None, cache_file: str | None = None) -> None:
    """Store ``pr`` for ``key`` with a TTL, pruning expired entries.

    Best-effort and atomic: any IO error is swallowed so a render never fails
    on a cache write. A shorter ``ttl`` negatively caches a failed lookup.
    ``cache_file`` defaults to :func:`_pr_cache_file`; callers that redirect
    the location at their own module namespace pass it explicitly.
    """
    try:
        path = cache_file or _pr_cache_file()
        now = time.time()
        try:
            with open(path, encoding="utf-8") as fh:
                cache = json.load(fh)
            if not isinstance(cache, dict):
                cache = {}
        except (OSError, ValueError):
            cache = {}
        cache = {k: v for k, v in cache.items() if isinstance(v, dict) and v.get("exp", 0) > now}
        cache[key] = {
            "pr": pr,
            "exp": now + (ttl if ttl is not None else _PR_CACHE_TTL_SECONDS),
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(cache, fh)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Git info
# ---------------------------------------------------------------------------


def git_info(project_dir, magenta=None, cyan=None, reset: str = RESET) -> str:
    """Get git branch and change count for a directory.

    Accepts a `.git` directory OR worktree/submodule pointer file (F-BUG-007);
    a bogus `.git` entry fails cleanly because the git commands below fail
    and yield "".
    """
    if magenta is None:
        magenta = MAGENTA
    if cyan is None:
        cyan = CYAN
    git_dir = os.path.join(project_dir, ".git")
    if not os.path.exists(git_dir):
        return ""

    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ""
        branch = result.stdout.strip()

        if not branch:
            return ""

        result = subprocess.run(
            ["git", "--no-optional-locks", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            changes = 0
        else:
            changes = len([line for line in result.stdout.split("\n") if line.strip()])

        if changes > 0:
            return f" | {magenta}{branch}{reset} {cyan}[{changes}]{reset}"
        return f" | {magenta}{branch}{reset}"
    except (subprocess.TimeoutExpired, OSError):
        return ""
