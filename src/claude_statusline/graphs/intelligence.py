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
from typing import Any

from claude_statusline._shared import _ZONE_RECOMMENDATIONS as _ZONE_RECOMMENDATIONS

# Single-sourced in _shared (Task 5.2, F-DEAD-001); the standalone script loads
# the same bodies from claude_statusline._shared / its vendored copy. Names the
# package public API exposes are re-exported in explicit ``as`` form below.
from claude_statusline._shared import (
    LARGE_MODEL_THRESHOLD as LARGE_MODEL_THRESHOLD,
)
from claude_statusline._shared import (
    MI_CONTEXT_RED_THRESHOLD as MI_CONTEXT_RED_THRESHOLD,
)
from claude_statusline._shared import (
    MI_CONTEXT_YELLOW_THRESHOLD as MI_CONTEXT_YELLOW_THRESHOLD,
)
from claude_statusline._shared import (
    MI_GREEN_THRESHOLD as MI_GREEN_THRESHOLD,
)
from claude_statusline._shared import (
    MI_YELLOW_THRESHOLD as MI_YELLOW_THRESHOLD,
)
from claude_statusline._shared import (
    MODEL_PROFILES as MODEL_PROFILES,
)
from claude_statusline._shared import (
    PACMAN_ICONS as PACMAN_ICONS,
)
from claude_statusline._shared import (
    ZONE_1M_C_MAX as ZONE_1M_C_MAX,
)
from claude_statusline._shared import (
    ZONE_1M_D_MAX as ZONE_1M_D_MAX,
)
from claude_statusline._shared import (
    ZONE_1M_P_MAX as ZONE_1M_P_MAX,
)
from claude_statusline._shared import (
    ZONE_1M_PRICING_MAX as ZONE_1M_PRICING_MAX,
)
from claude_statusline._shared import (
    ZONE_1M_X_MAX as ZONE_1M_X_MAX,
)
from claude_statusline._shared import (
    ZONE_STD_DEAD_ZONE as ZONE_STD_DEAD_ZONE,
)
from claude_statusline._shared import (
    ZONE_STD_DUMP_ZONE as ZONE_STD_DUMP_ZONE,
)
from claude_statusline._shared import (
    ZONE_STD_HARD_LIMIT as ZONE_STD_HARD_LIMIT,
)
from claude_statusline._shared import (
    ZONE_STD_WARN_BUFFER as ZONE_STD_WARN_BUFFER,
)
from claude_statusline._shared import calculate_context_pressure as calculate_context_pressure
from claude_statusline._shared import context_zone_tuple, mi_color_name
from claude_statusline._shared import get_model_profile as get_model_profile
from claude_statusline._shared import get_pacman_icon as get_pacman_icon
from claude_statusline.core.state import StateEntry


@dataclass
class ZoneInfo:
    """Context zone indicator with color and actionable recommendation."""

    zone: str  # "Plan", "Code", "Dump", "ExDump", or "Dead"
    color: str  # "green", "yellow", "orange", "dark_red", or "gray"
    label: str  # Human-readable label
    recommendation: str  # One-line action guidance for the user


# Lookup table (Task 5.6, F-CLEAN-006): field names of the zone-threshold
# bundle, in the order ``_shared.context_zone_tuple`` consumes them. Drives
# both config extraction and the override expansion — adding a threshold
# means touching this tuple and the dataclass only.
_ZONE_THRESHOLD_FIELDS: tuple[str, ...] = (
    "zone_1m_plan_max",
    "zone_pricing_max",
    "zone_1m_code_max",
    "zone_1m_dump_max",
    "zone_1m_xdump_max",
    "zone_std_dump_ratio",
    "zone_std_warn_buffer",
    "zone_std_hard_limit",
    "zone_std_dead_ratio",
    "large_model_threshold",
)


@dataclass(frozen=True)
class ZoneThresholds:
    """Bundle of zone threshold overrides (Task 5.6, F-CLEAN-006).

    Every field mirrors a Config attribute of the same name; a value of
    0 (or 0.0) means "use the shared module-level default".
    """

    zone_1m_plan_max: int = 0
    zone_pricing_max: int = 0
    zone_1m_code_max: int = 0
    zone_1m_dump_max: int = 0
    zone_1m_xdump_max: int = 0
    zone_std_dump_ratio: float = 0.0
    zone_std_warn_buffer: int = 0
    zone_std_hard_limit: float = 0.0
    zone_std_dead_ratio: float = 0.0
    large_model_threshold: int = 0

    @classmethod
    def from_config(cls, config: Any) -> ZoneThresholds:
        """Extract the bundle from a Config's same-named attributes."""
        return cls(**{name: getattr(config, name) for name in _ZONE_THRESHOLD_FIELDS})

    def overrides(self) -> dict[str, Any]:
        """Keyword form consumed by ``_shared.context_zone_tuple``."""
        return {name: getattr(self, name) for name in _ZONE_THRESHOLD_FIELDS}


# Zone recommendation strings and pacman glyphs are single-sourced in _shared
# (imported above as _ZONE_RECOMMENDATIONS / PACMAN_ICONS).


@dataclass
class IntelligenceScore:
    """MI score with utilization info."""

    mi: float
    utilization: float


# get_model_profile / calculate_context_pressure are single-sourced in _shared;
# re-exported here under their historical names for the package public API.


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
    thresholds: ZoneThresholds | None = None,
) -> ZoneInfo:
    """Determine the context zone indicator based on token usage.

    For 1M models (context_window >= large threshold):
      P: < zone_1m_plan_max used
      Price: plan_max–pricing_max used (cost warning band)
      C: pricing_max–code_max used
      D: code_max–dump_max used
      X: dump_max–xdump_max used
      Z: >= xdump_max used

    For standard models (< large threshold):
      P: below the warn buffer
      C: warn buffer to dump ratio (40%)
      D: 40%–70% utilization
      X: 70%–75% utilization
      Z: >= dead ratio (75%) utilization

    Threshold overrides travel as one :class:`ZoneThresholds` bundle
    (Task 5.6, F-CLEAN-006) instead of eleven keyword parameters; a field
    of 0 (or 0.0) means "use the module-level default".

    Args:
        used_tokens: Number of tokens currently used
        context_window_size: Total context window size in tokens
        thresholds: Optional threshold bundle; defaults when omitted

    Returns:
        ZoneInfo with zone letter, color name, and label
    """
    effective = thresholds if thresholds is not None else ZoneThresholds()
    zone, color, recommendation = context_zone_tuple(
        used_tokens,
        context_window_size,
        **effective.overrides(),
    )
    return ZoneInfo(
        zone=zone,
        color=color,
        label=_ZONE_LABELS[zone],
        recommendation=recommendation,
    )


# Human-readable labels per zone (package-only presentation detail)
_ZONE_LABELS: dict[str, str] = {
    "Plan": "Planning",
    "Pricing": "Pricing tier",
    "Code": "Code-only",
    "Dump": "Dump zone",
    "ExDump": "Hard limit",
    "Dead": "Dead zone",
}


# Pacman icon mapping is single-sourced in _shared; re-exported under the
# historical name for the package public API.


def get_mi_color(mi: float, utilization: float = 0.0) -> str:
    """Get color name for MI score considering both MI and context utilization.

    Returns:
        Color name: "green", "yellow", or "red"
    """
    return mi_color_name(mi, utilization)


def format_mi_score(mi: float) -> str:
    """Format MI score for display.

    Args:
        mi: MI score value

    Returns:
        Formatted string like "0.823"
    """
    return f"{mi:.3f}"
