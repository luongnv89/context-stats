"""Model Intelligence (MI) score computation.

Estimates answer quality degradation based on context utilization.
Calibrated from MRCR v2 8-needle benchmark data showing that retrieval
quality degrades monotonically with context length, at different rates
per model family.

Formula: MI(u) = max(0, 1 - u^beta)
Where u = utilization ratio, beta is model-specific.
Higher beta = quality retained longer (degradation happens later).

Zone indicators provide a quick signal for session state and recommended action:
  Plan   = Planning mode (green)    — safe to plan and code
  Code   = Code-only mode (yellow)  — avoid starting new tasks; finish current one
  Dump   = Dump zone (orange)       — consider /compact or delegate to subagent
  ExDump = Hard limit (dark red)    — run /compact now before quality degrades further
  Dead   = Dead zone (gray)         — start a new session with /clear

1M model thresholds calibrated from observed context rot onset at 300-400k tokens.
Source: x.com/trq212/status/2044548257058328723 ("Every Turn Is a Branching Point")
"""

from __future__ import annotations

from dataclasses import dataclass

from claude_statusline.core.state import StateEntry

# MI color thresholds — based on MI value and context utilization
MI_GREEN_THRESHOLD = 0.90
MI_YELLOW_THRESHOLD = 0.80
# Context utilization zones (used as fallback for color decisions)
MI_CONTEXT_YELLOW_THRESHOLD = 0.40  # 40% context used
MI_CONTEXT_RED_THRESHOLD = 0.80  # 80% context used

# 1M model detection threshold (context windows >= 500k are treated as 1M-class)
LARGE_MODEL_THRESHOLD = 500_000

# Zone thresholds for 1M models (token counts)
# Recalibrated to match observed context rot onset at 300-400k tokens.
# See: x.com/trq212/status/2044548257058328723
ZONE_1M_P_MAX = 150_000  # P zone: < 150k used
ZONE_1M_C_MAX = 250_000  # C zone: 150k–250k used
ZONE_1M_D_MAX = 400_000  # D zone: 250k–400k used
ZONE_1M_X_MAX = 450_000  # X zone: 400k–450k used; Z zone: >= 450k

# Zone thresholds for standard models (< 1M) — expressed as utilization ratios
ZONE_STD_DUMP_ZONE = 0.40  # dump zone starts at 40%
ZONE_STD_WARN_BUFFER = 30_000  # warn 30k tokens before dump zone
ZONE_STD_HARD_LIMIT = 0.70  # hard limit at 70%
ZONE_STD_DEAD_ZONE = 0.75  # dead zone starts at 75%

# Per-model degradation profiles calibrated from MRCR v2 8-needle benchmark
# beta controls curve shape: higher = quality retained longer
# All models drop from 1.0 to 0.0, but at different rates
MODEL_PROFILES: dict[str, float] = {
    "opus": 1.8,  # retains quality longest, steep drop near end
    "sonnet": 1.5,  # moderate degradation
    "haiku": 1.2,  # degrades earliest
    "default": 1.5,  # same as sonnet
}


@dataclass
class ZoneInfo:
    """Context zone indicator with color and actionable recommendation."""

    zone: str  # "Plan", "Code", "Dump", "ExDump", or "Dead"
    color: str  # "green", "yellow", "orange", "dark_red", or "gray"
    label: str  # Human-readable label
    recommendation: str  # One-line action guidance for the user

# Zone recommendation strings — one per zone
_ZONE_RECOMMENDATIONS: dict[str, str] = {
    "Plan": "Safe to plan and code",
    "Code": "Avoid starting new tasks; finish current one",
    "Dump": "Consider `/compact focus on X` or delegate to subagent",
    "ExDump": "Run `/compact` now before quality degrades further",
    "Dead": "Start a new session with `/clear`",
}


@dataclass
class IntelligenceScore:
    """MI score with utilization info."""

    mi: float
    utilization: float


def get_model_profile(model_id: str) -> float:
    """Match model_id to degradation beta.

    Args:
        model_id: Model identifier string (e.g., "claude-opus-4-6[1m]")

    Returns:
        Beta value for the model's degradation curve
    """
    model_lower = model_id.lower()
    for family in ("opus", "sonnet", "haiku"):
        if family in model_lower:
            return MODEL_PROFILES[family]
    return MODEL_PROFILES["default"]


def calculate_context_pressure(utilization: float, beta: float = 1.5) -> float:
    """Calculate Model Intelligence from context utilization.

    MI = max(0, 1 - u^beta)

    Args:
        utilization: Context utilization ratio (current_used / context_window_size)
        beta: Curve shape parameter (model-specific)

    Returns:
        MI value in [0, 1]
    """
    if utilization <= 0:
        return 1.0
    return max(0.0, 1.0 - utilization**beta)


def calculate_intelligence(
    current: StateEntry,
    context_window_size: int,
    model_id: str = "",
    beta_override: float = 0.0,
) -> IntelligenceScore:
    """Calculate Model Intelligence score.

    Args:
        current: Current state entry
        context_window_size: Total context window size in tokens
        model_id: Model identifier for profile lookup
        beta_override: If > 0, overrides model profile beta

    Returns:
        IntelligenceScore with MI and utilization
    """
    # Guard clause: unknown context window
    if context_window_size == 0:
        return IntelligenceScore(mi=1.0, utilization=0.0)

    beta_from_profile = get_model_profile(model_id or current.model_id)
    beta = beta_override if beta_override > 0 else beta_from_profile

    utilization = current.current_used_tokens / context_window_size
    mi = calculate_context_pressure(utilization, beta)

    return IntelligenceScore(mi=mi, utilization=utilization)


def get_context_zone(
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
) -> ZoneInfo:
    """Determine the context zone indicator based on token usage.

    For 1M models (context_window >= 500k):
      P: < 150k used
      C: 150k–250k used
      D: 250k–400k used
      X: 400k–450k used
      Z: >= 450k used

    For standard models (< 500k context):
      P: < (dump_zone - 30k)
      C: (dump_zone - 30k) to dump_zone (40%)
      D: 40%–70% utilization
      X: 70%–75% utilization
      Z: >= 75% utilization

    All thresholds can be overridden via keyword arguments.
    A value of 0 (or 0.0) means "use the module-level default".

    Args:
        used_tokens: Number of tokens currently used
        context_window_size: Total context window size in tokens
        zone_1m_plan_max: Override for ZONE_1M_P_MAX
        zone_1m_code_max: Override for ZONE_1M_C_MAX
        zone_1m_dump_max: Override for ZONE_1M_D_MAX
        zone_1m_xdump_max: Override for ZONE_1M_X_MAX
        zone_std_dump_ratio: Override for ZONE_STD_DUMP_ZONE
        zone_std_warn_buffer: Override for ZONE_STD_WARN_BUFFER
        zone_std_hard_limit: Override for ZONE_STD_HARD_LIMIT
        zone_std_dead_ratio: Override for ZONE_STD_DEAD_ZONE
        large_model_threshold: Override for LARGE_MODEL_THRESHOLD

    Returns:
        ZoneInfo with zone letter, color name, and label
    """
    if context_window_size == 0:
        return ZoneInfo(
            zone="Plan", color="green", label="Planning",
            recommendation=_ZONE_RECOMMENDATIONS["Plan"],
        )

    # Apply overrides (0 = use default)
    lmt = large_model_threshold or LARGE_MODEL_THRESHOLD
    is_large_model = context_window_size >= lmt

    if is_large_model:
        p_max = zone_1m_plan_max or ZONE_1M_P_MAX
        c_max = zone_1m_code_max or ZONE_1M_C_MAX
        d_max = zone_1m_dump_max or ZONE_1M_D_MAX
        x_max = zone_1m_xdump_max or ZONE_1M_X_MAX

        if used_tokens < p_max:
            return ZoneInfo(
                zone="Plan", color="green", label="Planning",
                recommendation=_ZONE_RECOMMENDATIONS["Plan"],
            )
        if used_tokens < c_max:
            return ZoneInfo(
                zone="Code", color="yellow", label="Code-only",
                recommendation=_ZONE_RECOMMENDATIONS["Code"],
            )
        if used_tokens < d_max:
            return ZoneInfo(
                zone="Dump", color="orange", label="Dump zone",
                recommendation=_ZONE_RECOMMENDATIONS["Dump"],
            )
        if used_tokens < x_max:
            return ZoneInfo(
                zone="ExDump", color="dark_red", label="Hard limit",
                recommendation=_ZONE_RECOMMENDATIONS["ExDump"],
            )
        return ZoneInfo(
            zone="Dead", color="gray", label="Dead zone",
            recommendation=_ZONE_RECOMMENDATIONS["Dead"],
        )

    # Standard models
    dump_ratio = zone_std_dump_ratio or ZONE_STD_DUMP_ZONE
    warn_buf = zone_std_warn_buffer or ZONE_STD_WARN_BUFFER
    hard_lim = zone_std_hard_limit or ZONE_STD_HARD_LIMIT
    dead_rat = zone_std_dead_ratio or ZONE_STD_DEAD_ZONE

    dump_zone_tokens = int(context_window_size * dump_ratio)
    warn_start = max(0, dump_zone_tokens - warn_buf)
    hard_limit_tokens = int(context_window_size * hard_lim)
    dead_zone_tokens = int(context_window_size * dead_rat)

    if used_tokens < warn_start:
        return ZoneInfo(
            zone="Plan", color="green", label="Planning",
            recommendation=_ZONE_RECOMMENDATIONS["Plan"],
        )
    if used_tokens < dump_zone_tokens:
        return ZoneInfo(
            zone="Code", color="yellow", label="Code-only",
            recommendation=_ZONE_RECOMMENDATIONS["Code"],
        )
    if used_tokens < hard_limit_tokens:
        return ZoneInfo(
            zone="Dump", color="orange", label="Dump zone",
            recommendation=_ZONE_RECOMMENDATIONS["Dump"],
        )
    if used_tokens < dead_zone_tokens:
        return ZoneInfo(
            zone="ExDump", color="dark_red", label="Hard limit",
            recommendation=_ZONE_RECOMMENDATIONS["ExDump"],
        )
    return ZoneInfo(
        zone="Dead", color="gray", label="Dead zone",
        recommendation=_ZONE_RECOMMENDATIONS["Dead"],
    )


def get_mi_color(mi: float, utilization: float = 0.0) -> str:
    """Get color name for MI score considering both MI and context utilization.

    Rules:
      - Green: MI >= 0.90
      - Yellow: MI < 0.90 and > 0.80, OR context 40%-80%
      - Red: MI <= 0.80, OR context > 80%

    Args:
        mi: MI score value
        utilization: Context utilization ratio (0-1)

    Returns:
        Color name: "green", "yellow", or "red"
    """
    # Red: MI critically low or context nearly full
    if mi <= MI_YELLOW_THRESHOLD or utilization >= MI_CONTEXT_RED_THRESHOLD:
        return "red"
    # Yellow: MI degrading or context in warning zone
    if mi < MI_GREEN_THRESHOLD or utilization >= MI_CONTEXT_YELLOW_THRESHOLD:
        return "yellow"
    return "green"


def format_mi_score(mi: float) -> str:
    """Format MI score for display.

    Args:
        mi: MI score value

    Returns:
        Formatted string like "0.823"
    """
    return f"{mi:.3f}"
