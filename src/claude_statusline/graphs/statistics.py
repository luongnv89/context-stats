"""Statistical calculations for token data."""

from __future__ import annotations

from dataclasses import dataclass

# tok/s + compaction primitives are single-sourced in _shared (Task 5.2,
# F-DEAD-001); the standalone script loads the same bodies from
# claude_statusline._shared / its vendored copy.
from claude_statusline._shared import (
    COMPACTION_DROP_THRESHOLD as COMPACTION_DROP_THRESHOLD,
)
from claude_statusline._shared import compute_tps as compute_tps
from claude_statusline._shared import detect_compaction_events as detect_compaction_events
from claude_statusline._shared import format_tps as format_tps


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


# detect_compaction_events / compute_tps / format_tps bodies are single-sourced
# in _shared (imported above). The default-threshold semantics are preserved:
# the shared detect_compaction_events resolves drop_threshold=None to
# COMPACTION_DROP_THRESHOLD (0.5), matching the former 0.5 literal default.


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


def compute_tps_series(
    samples: list[tuple[int, int]],
) -> list[tuple[int, float]]:
    """Build a per-turn instantaneous throughput series for trend plotting.

    Where :func:`compute_tps` collapses the recent turns into a single rolling
    number for the live statusline, this returns *one throughput point per
    valid turn* so the trend can be graphed over time. Each point is the
    instantaneous tok/s of a single turn, which is exactly what surfaces
    regressions and spikes (the motivation in issue #72).

    A *turn* is the transition between two consecutive ``samples``. The
    per-turn speed is computed by delegating to ``compute_tps(pair, 1)``, so
    the drop rules stay in one place: turns against a legacy/first row
    (cumulative duration ``<= 0``), with a non-positive API-time delta (same
    response refreshed twice), or with non-positive output are dropped and
    simply omitted from the series — never plotted as a zero.

    Each returned tuple is ``(sample_index, tokens_per_second)`` where
    ``sample_index`` is the index *into ``samples``* of the turn's *later*
    sample (i.e. the row whose output was produced). Callers use that index to
    line up the matching timestamp for the x-axis, which is why the index is
    returned alongside the value rather than discarded — a dropped turn must
    not desynchronise values from their timestamps.

    Args:
        samples: Chronological ``(output_tokens, api_duration_ms)`` pairs, one
            per state row, oldest first. ``api_duration_ms`` is the cumulative
            API wait time at that row (CSV index 14).

    Returns:
        Chronological list of ``(sample_index, tok_per_second)`` for every
        valid turn. Empty when no valid turn exists (first row, all-legacy
        history, or no real API time elapsed).
    """
    series: list[tuple[int, float]] = []
    for i in range(1, len(samples)):
        # Reuse the single-turn path so the legacy/zero-delta/zero-output drop
        # semantics are inherited verbatim from compute_tps rather than
        # re-implemented here.
        tps = compute_tps([samples[i - 1], samples[i]], window=1)
        if tps is None:
            continue
        series.append((i, tps))
    return series
