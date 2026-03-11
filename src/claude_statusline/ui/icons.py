"""Activity tier detection for token usage visualization."""

from __future__ import annotations

from enum import Enum

from claude_statusline.core.state import StateEntry
from claude_statusline.graphs.statistics import calculate_deltas, detect_spike


class ActivityTier(Enum):
    """Token activity intensity tiers."""

    IDLE = "idle"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SPIKE = "spike"


# Tier labels for accessibility (understandable without color)
TIER_LABELS: dict[ActivityTier, str] = {
    ActivityTier.IDLE: "Idle",
    ActivityTier.LOW: "Low activity",
    ActivityTier.MEDIUM: "Active",
    ActivityTier.HIGH: "High activity",
    ActivityTier.SPIKE: "Spike!",
}


def get_activity_tier(
    entries: list[StateEntry],
    context_window_size: int,
) -> ActivityTier:
    """Determine the current activity tier based on recent token deltas.

    Args:
        entries: List of StateEntry objects (chronological order)
        context_window_size: Total context window size in tokens

    Returns:
        The current ActivityTier
    """
    if len(entries) < 2:
        return ActivityTier.IDLE

    # Check if session is idle (>30s since last entry)
    import time

    now = int(time.time())
    last_timestamp = entries[-1].timestamp
    if now - last_timestamp > 30:
        return ActivityTier.IDLE

    # Calculate deltas from context usage
    context_used = [e.current_used_tokens for e in entries]
    deltas = calculate_deltas(context_used)

    if not deltas:
        return ActivityTier.IDLE

    latest_delta = deltas[-1]

    if context_window_size <= 0:
        return ActivityTier.LOW if latest_delta > 0 else ActivityTier.IDLE

    # Check for spike first (highest priority)
    if detect_spike(deltas, context_window_size):
        return ActivityTier.SPIKE

    # Calculate delta as percentage of context window
    delta_pct = (latest_delta / context_window_size) * 100

    if delta_pct > 5:
        return ActivityTier.HIGH
    elif delta_pct > 2:
        return ActivityTier.MEDIUM
    elif latest_delta > 0:
        return ActivityTier.LOW
    else:
        return ActivityTier.IDLE


def get_tier_label(tier: ActivityTier) -> str:
    """Get an accessible text label for a tier.

    Args:
        tier: The activity tier

    Returns:
        Human-readable label string
    """
    return TIER_LABELS.get(tier, "")
