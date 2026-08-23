"""Token formatting utilities."""

from __future__ import annotations

from claude_statusline._shared import AUTOCOMPACT_RATIO


def format_tokens(count: int, detail: bool = True) -> str:
    """Format token count for display.

    Args:
        count: Number of tokens
        detail: If True, show exact count with commas. If False, use abbreviated format.

    Returns:
        Formatted string like "64,000" or "64.0k"
    """
    if detail:
        return f"{count:,}"
    else:
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}k"
        else:
            return str(count)


def calculate_context_usage(
    used_tokens: int,
    total_size: int,
    autocompact_enabled: bool = True,
    autocompact_ratio: float = AUTOCOMPACT_RATIO,
) -> tuple[int, float, int]:
    """Calculate context window usage statistics.

    Args:
        used_tokens: Number of tokens currently used
        total_size: Total context window size
        autocompact_enabled: Whether autocompact is enabled
        autocompact_ratio: Ratio of context window reserved for autocompact (default 22.5%)

    Returns:
        Tuple of (free_tokens, free_percentage, autocompact_buffer)
    """
    if total_size <= 0:
        return 0, 0.0, 0

    autocompact_buffer = int(total_size * autocompact_ratio)

    if autocompact_enabled:
        free_tokens = total_size - used_tokens - autocompact_buffer
    else:
        free_tokens = total_size - used_tokens

    free_tokens = max(0, free_tokens)
    free_pct = (free_tokens * 100.0) / total_size

    return free_tokens, free_pct, autocompact_buffer
