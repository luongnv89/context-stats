"""Statistical calculations for token data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Stats:
    """Statistical summary of a data series."""

    min_val: int
    max_val: int
    avg_val: int
    total: int
    count: int


def calculate_stats(data: list[int]) -> Stats:
    """Calculate basic statistics for a list of integers.

    Args:
        data: List of integer values

    Returns:
        Stats object with min, max, avg, total, and count
    """
    if not data:
        return Stats(min_val=0, max_val=0, avg_val=0, total=0, count=0)

    min_val = min(data)
    max_val = max(data)
    total = sum(data)
    count = len(data)
    avg_val = total // count if count > 0 else 0

    return Stats(min_val=min_val, max_val=max_val, avg_val=avg_val, total=total, count=count)


def detect_spike(deltas: list[int], context_window_size: int, window: int = 5) -> bool:
    """Check if the latest delta is a spike.

    A spike is defined as:
    - Latest delta > 15% of context window size, OR
    - Latest delta > 3x the rolling average of the last `window` deltas

    Args:
        deltas: List of token deltas
        context_window_size: Total context window size in tokens
        window: Number of recent deltas for rolling average (default: 5)

    Returns:
        True if the latest delta qualifies as a spike
    """
    if not deltas:
        return False

    latest = deltas[-1]

    # Check absolute threshold: > 15% of context window
    if context_window_size > 0 and latest > context_window_size * 0.15:
        return True

    # Check relative threshold: > 3x rolling average of previous deltas
    previous = deltas[-(window + 1) : -1] if len(deltas) > window else deltas[:-1]
    if previous:
        avg = sum(previous) / len(previous)
        if avg > 0 and latest > avg * 3:
            return True

    return False


def detect_compaction_events(
    values: list[int], drop_threshold: float = 0.5
) -> list[int]:
    """Detect compaction events in a list of token counts.

    A compaction event is identified when ``values[i] < values[i-1] * (1 - drop_threshold)``,
    i.e., the context dropped by more than *drop_threshold* fraction in a single step.
    With the default threshold of 0.5 this means the new value is less than half the old value.

    The parameter ``drop_threshold`` controls what fraction of context must be lost to count
    as a compaction.  Increasing it makes detection stricter (only very large drops qualify);
    decreasing it makes it more sensitive.

    Args:
        values: Sequence of token counts (e.g., ``current_used_tokens`` over time).
        drop_threshold: Fraction of context that must be lost to qualify as compaction
                        (default: 0.5, i.e., > 50 % drop).

    Returns:
        List of indices *i* (into *values*) where a compaction was detected.
        Indices are 1-based (the earliest possible index is 1).
    """
    if len(values) < 2:
        return []

    events: list[int] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        curr = values[i]
        # Guard against zero-division; if prev == 0 there is nothing to compare
        if prev > 0 and curr < prev * (1.0 - drop_threshold):
            events.append(i)
    return events


def calculate_deltas(values: list[int]) -> list[int]:
    """Calculate deltas between consecutive values.

    Args:
        values: List of values (e.g., cumulative token counts)

    Returns:
        List of deltas (length = len(values) - 1)
    """
    if len(values) < 2:
        return []

    deltas = []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        # Handle negative deltas (session reset) by showing 0
        deltas.append(max(0, delta))

    return deltas
