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
    samples: list[tuple[int, int]],
    window: int = 5,
) -> float | None:
    """Compute a smoothed, session-rolling model throughput in tokens/second.

    Rather than the jumpy per-turn instantaneous speed (which swings between,
    say, 1.5 and 80 tok/s depending on how many tokens a single turn happened
    to emit), this returns a **rolling, token-weighted average** over the most
    recent turns. The average is weighted by output tokens, so a tiny 3-token
    turn cannot drag the number down the way a plain mean-of-ratios would —
    the result tracks the genuine "speed of the model" across the session.

    Each ``sample`` is an ``(output_tokens, api_duration_ms)`` pair taken from
    a state row (plus the live reading), where ``api_duration_ms`` is the
    cumulative ``cost.total_api_duration_ms`` ("time spent waiting for API
    responses" — it excludes user idle time, tool execution, and thinking).
    A *turn* is the transition between two consecutive samples: its output is
    that row's ``current_usage.output_tokens`` and its API time is the delta
    of the cumulative durations. Turns with a non-positive API-time delta
    (same response refreshed twice) or non-positive output are dropped.

    The average over the last ``window`` valid turns is token-weighted:

        tok/s = Σ output_tokens / (Σ api_time_ms / 1000)

    Because both sums accumulate over the kept turns, a turn that contributes
    no valid sample simply isn't in the sums — the previously established
    average persists ("keep last average" on missing data) as long as at least
    one valid turn remains in the window.

    Args:
        samples: Chronological ``(output_tokens, api_duration_ms)`` pairs, one
            per state row, with the live reading last. ``api_duration_ms`` is
            the cumulative API wait time at that row.
        window: Number of most-recent valid turns to average over (>= 1).

    Returns:
        Rolling throughput in tokens/second, or ``None`` when no valid turn
        exists yet (first row, all legacy rows, or no real API time elapsed).
        ``None`` signals "hide the display".
    """
    if window < 1:
        window = 1

    # Reconstruct per-turn (output, api_time_ms) from consecutive samples,
    # keeping only turns with real elapsed API time and real output.
    turns: list[tuple[int, int]] = []
    for (_, prev_dur), (out, cur_dur) in zip(samples, samples[1:]):
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
