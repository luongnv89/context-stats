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


def detect_compaction_events(values: list[int], drop_threshold: float = 0.5) -> list[int]:
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


def compute_tps(
    current_output_tokens: int,
    api_duration_ms: int,
    prev_api_duration_ms: int,
) -> float | None:
    """Compute model throughput in tokens per second.

    Throughput is measured as the most recent API response's output tokens
    divided by the API time that response took. The API time is derived from
    the delta of the cumulative ``cost.total_api_duration_ms`` field between
    the current and previous state rows. ``total_api_duration_ms`` is "time
    spent waiting for API responses", so it excludes user idle time, tool
    execution, and thinking — yielding genuine model generation speed.

    The numerator uses ``current_usage.output_tokens`` (the most recent
    response's output) rather than a cumulative total, because as of Claude
    Code v2.1.132 ``context_window.total_output_tokens`` reflects current
    context usage, not a session total. ``current_usage.output_tokens`` has
    always meant "this request", so it stays aligned with the per-response
    API-time delta across versions.

    Args:
        current_output_tokens: Output tokens of the most recent response
            (``current_usage.output_tokens``).
        api_duration_ms: Cumulative API wait time so far
            (``cost.total_api_duration_ms``).
        prev_api_duration_ms: Cumulative API wait time from the previous
            state row.

    Returns:
        Throughput in tokens/second, or ``None`` when it cannot be computed
        meaningfully (no output, no prior reading, or non-positive elapsed
        API time). ``None`` signals "hide the display this cycle".
    """
    # Need a real previous reading to difference against. A zero previous
    # value means either no prior row or a legacy row without the field —
    # differencing against it would understate throughput badly.
    if prev_api_duration_ms <= 0:
        return None

    delta_ms = api_duration_ms - prev_api_duration_ms
    if delta_ms <= 0:
        # Same response refreshed twice, or no new API time elapsed.
        return None

    if current_output_tokens <= 0:
        return None

    return current_output_tokens / (delta_ms / 1000.0)


def format_tps(tps: float, precision: int = 1, unit: str = "tok/s") -> str:
    """Format a tokens-per-second value for display.

    Args:
        tps: Throughput in tokens per second.
        precision: Number of decimal places (clamped to >= 0).
        unit: Unit label appended after the value (e.g. ``"tok/s"``).

    Returns:
        Formatted string like ``"42.5 tok/s"``.
    """
    precision = max(0, precision)
    return f"{tps:.{precision}f} {unit}"
