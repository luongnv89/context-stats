"""ASCII graph rendering engine."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass

from claude_statusline.core.colors import ColorManager
from claude_statusline.formatters.time import format_duration, format_timestamp
from claude_statusline.formatters.tokens import format_tokens
from claude_statusline.graphs.statistics import calculate_stats


@dataclass
class GraphDimensions:
    """Terminal and graph dimensions."""

    term_width: int
    term_height: int
    graph_width: int
    graph_height: int

    @classmethod
    def detect(cls) -> GraphDimensions:
        """Detect terminal dimensions and calculate graph size."""
        term_size = shutil.get_terminal_size((80, 24))
        term_width = term_size.columns
        term_height = term_size.lines

        # Calculate graph dimensions
        graph_width = term_width - 15  # Reserve space for Y-axis labels
        graph_height = term_height // 3  # Each graph takes 1/3 of terminal

        # Enforce minimums and maximums
        graph_width = max(30, graph_width)
        graph_height = max(8, min(20, graph_height))

        return cls(
            term_width=term_width,
            term_height=term_height,
            graph_width=graph_width,
            graph_height=graph_height,
        )


class GraphRenderer:
    """ASCII graph rendering engine."""

    # Characters for graph rendering
    DOT = "●"
    FILL_LIGHT = "▒"
    FILL_DARK = "░"

    def __init__(
        self,
        colors: ColorManager | None = None,
        dimensions: GraphDimensions | None = None,
        token_detail: bool = True,
    ) -> None:
        """Initialize graph renderer.

        Args:
            colors: ColorManager instance. Creates default if None.
            dimensions: GraphDimensions instance. Detects if None.
            token_detail: Whether to show detailed token counts.
        """
        self.colors = colors or ColorManager(enabled=True)
        self.dimensions = dimensions or GraphDimensions.detect()
        self.token_detail = token_detail
        self._output_lines: list[str] | None = None

    def begin_buffering(self) -> None:
        """Start buffering output instead of printing directly."""
        self._output_lines = []

    def get_buffer(self) -> str:
        """Return buffered output as a single string and stop buffering."""
        if self._output_lines is None:
            return ""
        result = "\n".join(self._output_lines)
        self._output_lines = None
        return result

    def _emit(self, line: str = "") -> None:
        """Emit a line of output. Buffers if buffering is active, otherwise prints."""
        if self._output_lines is not None:
            self._output_lines.append(line)
        else:
            print(line)

    def render_timeseries(
        self,
        data: list[int],
        timestamps: list[int],
        title: str,
        color: str,
        label_fn: Callable[[int], str] | None = None,
    ) -> None:
        """Render a timeseries ASCII graph.

        Args:
            data: List of values to plot
            timestamps: Corresponding timestamps for x-axis labels
            title: Graph title
            color: ANSI color code for the graph
            label_fn: Optional function to format Y-axis labels. If None, uses format_tokens().
        """
        n = len(data)
        if n == 0:
            return

        stats = calculate_stats(data)
        min_val = stats.min_val
        max_val = stats.max_val

        # Avoid division by zero
        if min_val == max_val:
            max_val = min_val + 1
        value_range = max_val - min_val

        width = self.dimensions.graph_width
        height = self.dimensions.graph_height

        fmt = label_fn if label_fn else lambda v: format_tokens(v, self.token_detail)

        # Print title and stats
        self._emit()
        self._emit(f"{self.colors.bold}{title}{self.colors.reset}")
        self._emit(
            f"{self.colors.dim}Max: {fmt(max_val)}  "
            f"Min: {fmt(min_val)}  "
            f"Points: {n}{self.colors.reset}"
        )
        self._emit()

        # Build the graph grid
        grid = self._build_grid(data, min_val, max_val, value_range, width, height)

        # Print grid with Y-axis labels
        for r in range(height):
            val = max_val - r * value_range // (height - 1)

            # Show labels at top, middle, and bottom
            if r == 0 or r == height // 2 or r == height - 1:
                label = fmt(val)
            else:
                label = ""

            row_data = grid[r] if r < len(grid) else " " * width
            self._emit(
                f"{label:>10} {self.colors.dim}│{self.colors.reset}"
                f"{color}{row_data}{self.colors.reset}"
            )

        # X-axis
        self._emit(f"{'':>10} {self.colors.dim}└{'─' * width}{self.colors.reset}")

        # Time labels
        if timestamps:
            first_time = format_timestamp(timestamps[0])
            last_time = format_timestamp(timestamps[-1])
            mid_idx = (n - 1) // 2
            mid_time = format_timestamp(timestamps[mid_idx]) if n > 2 else ""

            spacing = width // 3
            self._emit(
                f"{' ':>11}{self.colors.dim}"
                f"{first_time:<{spacing}}{mid_time}{last_time:>{spacing}}"
                f"{self.colors.reset}"
            )

    def _build_grid(
        self,
        data: list[int],
        min_val: int,
        max_val: int,
        value_range: int,
        width: int,
        height: int,
    ) -> list[str]:
        """Build the ASCII grid for the graph.

        Args:
            data: List of values to plot
            min_val: Minimum value in data
            max_val: Maximum value in data
            value_range: max_val - min_val
            width: Graph width in characters
            height: Graph height in rows

        Returns:
            List of strings, one per row
        """
        n = len(data)
        if n == 0:
            return [" " * width for _ in range(height)]

        # Initialize grid with empty spaces
        grid = [[" " for _ in range(width)] for _ in range(height)]

        # Calculate y positions for each data point
        data_x = []
        data_y = []
        for i, val in enumerate(data):
            # Map index to x coordinate
            if n == 1:
                x = width // 2
            else:
                x = int((i) * (width - 1) / (n - 1))
            x = max(0, min(width - 1, x))

            # Map value to y coordinate (inverted: 0=top)
            if value_range == 0:
                y = height // 2
            else:
                y = int((max_val - val) * (height - 1) / value_range)
            y = max(0, min(height - 1, y))

            data_x.append(x)
            data_y.append(y)

        # Interpolate between points to fill every x position
        line_y = [-1.0] * width
        for i in range(len(data) - 1):
            x1, y1 = data_x[i], data_y[i]
            x2, y2 = data_x[i + 1], data_y[i + 1]

            # Ensure we don't go out of bounds
            for x in range(x1, min(x2 + 1, width)):
                if x2 == x1:
                    y_interp = float(y1)
                else:
                    # Linear interpolation
                    t = (x - x1) / (x2 - x1)
                    y_interp = y1 + t * (y2 - y1)
                line_y[x] = y_interp

        # Draw filled area and line
        for c in range(width):
            if line_y[c] >= 0:
                line_row = int(line_y[c] + 0.5)  # Round to nearest integer
                line_row = max(0, min(height - 1, line_row))

                # Fill area below the line with gradient
                for r in range(line_row, height):
                    if r == line_row:
                        grid[r][c] = self.DOT
                    elif r < line_row + 2:
                        grid[r][c] = self.FILL_LIGHT
                    else:
                        grid[r][c] = self.FILL_DARK

        # Mark actual data points
        for i in range(len(data)):
            x = data_x[i]
            y = max(0, min(height - 1, int(data_y[i] + 0.5)))
            grid[y][x] = self.DOT

        # Convert grid to strings
        return ["".join(row) for row in grid]

    def render_summary(
        self,
        entries: list,  # list[StateEntry]
        deltas: list[int],
        mi_score: object | None = None,  # IntelligenceScore
        graph_type: str | None = None,
        cache_warm_status: tuple[bool, int] | None = None,
    ) -> None:
        """Render summary statistics.

        Args:
            entries: List of StateEntry objects
            deltas: List of token deltas
            mi_score: Optional IntelligenceScore for MI display
            graph_type: Graph type being displayed
            cache_warm_status: Optional (active, seconds_remaining) from cache_warm module
        """
        if not entries:
            return

        first = entries[0]
        last = entries[-1]
        duration = last.timestamp - first.timestamp

        # Context window info - use current_used_tokens which represents actual context usage
        remaining_context = 0
        remaining_percentage = 0
        usage_percentage = 0
        if last.context_window_size > 0:
            # current_used_tokens = current_input_tokens + cache_creation + cache_read
            current_used = last.current_used_tokens
            remaining_context = max(0, last.context_window_size - current_used)
            remaining_percentage = remaining_context * 100 // last.context_window_size
            usage_percentage = 100 - remaining_percentage

        # Determine status based on context usage
        if usage_percentage < 40:
            status_color = self.colors.green
            status_text = "Smart Zone"
            status_hint = "You are in the smart zone"
        elif usage_percentage < 80:
            status_color = self.colors.yellow
            status_text = "Dumb Zone"
            status_hint = "You are in the dumb zone - Dex Horthy says so"
        else:
            status_color = self.colors.red
            status_text = "Wrap Up Zone"
            status_hint = "Better to wrap up and start a new session"

        self._emit()
        self._emit(f"{self.colors.bold}Session Summary{self.colors.reset}")
        line_width = self.dimensions.graph_width + 11
        self._emit(f"{self.colors.dim}{'-' * line_width}{self.colors.reset}")

        # Context remaining (before status)
        if last.context_window_size > 0:
            self._emit(
                f"  {status_color}{'Context Remaining:':<20}{self.colors.reset} "
                f"{format_tokens(remaining_context, self.token_detail)}/{format_tokens(last.context_window_size, self.token_detail)} ({remaining_percentage}%)"
            )

        # Status indicator - highlighted
        if last.context_window_size > 0:
            self._emit(
                f"  {status_color}{self.colors.bold}>>> {status_text.upper()} <<<{self.colors.reset} "
                f"{self.colors.dim}({status_hint}){self.colors.reset}"
            )

        # Model Intelligence score
        if mi_score is not None:
            from claude_statusline.graphs.intelligence import (
                format_mi_score,
                get_mi_color,
            )

            mi_color_name = get_mi_color(mi_score.mi, mi_score.utilization)
            mi_color = getattr(self.colors, mi_color_name)
            if mi_color_name == "green":
                mi_hint = "Model is operating well"
            elif mi_color_name == "yellow":
                mi_hint = "Context pressure building, consider wrapping up"
            else:
                mi_hint = "Significant degradation, start new session"
            self._emit(
                f"  {mi_color}{'Model Intelligence:':<20}{self.colors.reset} "
                f"{format_mi_score(mi_score.mi)}  "
                f"{self.colors.dim}({mi_hint}){self.colors.reset}"
            )
            self._emit(
                f"  {self.colors.dim}  Context: "
                f"{mi_score.utilization * 100:.0f}% used{self.colors.reset}"
            )

        if last.context_window_size > 0:
            self._emit()

        # Session details (ordered: Last Growth, I/O, Lines, Cost, Model, Duration)
        if deltas:
            current_growth = deltas[-1]
            self._emit(
                f"  {self.colors.cyan}{'Last Growth:':<20}{self.colors.reset} "
                f"+{format_tokens(current_growth, self.token_detail)}"
            )
        self._emit(
            f"  {self.colors.blue}{'Input Tokens:':<20}{self.colors.reset} "
            f"{format_tokens(last.current_input_tokens, self.token_detail)}"
        )
        self._emit(
            f"  {self.colors.magenta}{'Output Tokens:':<20}{self.colors.reset} "
            f"{format_tokens(last.current_output_tokens, self.token_detail)}"
        )
        if last.cache_creation > 0 or last.cache_read > 0:
            self._emit(
                f"  {self.colors.red}{'Cache Creation:':<20}{self.colors.reset} "
                f"{format_tokens(last.cache_creation, self.token_detail)}"
            )
            self._emit(
                f"  {self.colors.cyan}{'Cache Read:':<20}{self.colors.reset} "
                f"{format_tokens(last.cache_read, self.token_detail)}"
            )
        if graph_type in ("cache", "all"):
            # Show cache TTL countdown after cache stats
            last_cache_ts = None
            for entry in reversed(entries):
                if entry.cache_creation > 0:
                    last_cache_ts = entry.timestamp
                    break
            if last_cache_ts is not None:
                import time

                elapsed = int(time.time()) - last_cache_ts
                ttl_remaining = max(0, 300 - elapsed)
                if ttl_remaining > 0:
                    ttl_text = format_duration(ttl_remaining, precise=True)
                    self._emit(
                        f"  {self.colors.yellow}{'Cache TTL:':<20}"
                        f"{self.colors.reset} {ttl_text}"
                    )
                else:
                    self._emit(
                        f"  {self.colors.yellow}{'Cache TTL:':<20}"
                        f"{self.colors.red}{self.colors.bold}expired{self.colors.reset}"
                    )
        if last.lines_added > 0 or last.lines_removed > 0:
            self._emit(
                f"  {self.colors.dim}{'Lines Changed:':<20}{self.colors.reset} "
                f"{self.colors.green}+{last.lines_added:,}{self.colors.reset} / "
                f"{self.colors.red}-{last.lines_removed:,}{self.colors.reset}"
            )
        if last.cost_usd > 0:
            self._emit(
                f"  {self.colors.yellow}{'Total Cost:':<20}{self.colors.reset} ${last.cost_usd:.4f}"
            )
        if last.model_id:
            self._emit(f"  {self.colors.dim}{'Model:':<20}{self.colors.reset} {last.model_id}")
        self._emit(
            f"  {self.colors.cyan}{'Session Duration:':<20}{self.colors.reset} "
            f"{format_duration(duration)}"
        )
        if cache_warm_status is not None:
            active, remaining = cache_warm_status
            if active:
                mins = remaining // 60
                secs = remaining % 60
                warm_time = f"{mins}m {secs}s" if mins else f"{secs}s"
                self._emit(
                    f"  {self.colors.green}{'Cache Warm:':<20}{self.colors.reset} "
                    f"active ({warm_time} remaining)"
                )
            else:
                self._emit(
                    f"  {self.colors.dim}{'Cache Warm:':<20}{self.colors.reset} inactive"
                )
        self._emit()

    def render_footer(self, version: str = "1.6.1", commit_hash: str = "dev") -> None:
        """Render the footer with version info.

        Args:
            version: Package version
            commit_hash: Git commit hash
        """
        self._emit(
            f"{self.colors.dim}Powered by {self.colors.cyan}cc-context-stats"
            f"{self.colors.dim} v{version}-{commit_hash} - "
            f"https://github.com/luongnv89/cc-context-stats{self.colors.reset}"
        )
        self._emit()
