#!/bin/bash
# Context Stats Visualizer for Claude Code
# Displays ASCII graphs of token consumption over time
#
# Usage:
#   context-stats.sh [session_id] [options]
#
# Options:
#   --type <cumulative|delta|both>  Graph type to display (default: both)
#   --watch, -w [interval]          Real-time monitoring mode (default: 2s)
#   --no-color                      Disable color output
#   --help                          Show this help
#
# Examples:
#   context-stats.sh                        # Latest session, both graphs
#   context-stats.sh abc123                 # Specific session
#   context-stats.sh --type delta           # Only delta graph
#   context-stats.sh --watch                # Real-time mode (2s refresh)
#   context-stats.sh -w 5                   # Real-time mode (5s refresh)

# Note: This script is compatible with bash 3.2+ (macOS default)

# === CONFIGURATION ===
# shellcheck disable=SC2034
VERSION="1.9.1"
COMMIT_HASH="dev" # Will be replaced during installation
STATE_DIR=~/.claude/statusline
CONFIG_FILE=~/.claude/statusline.conf

# === COLOR DEFINITIONS ===
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# === GLOBAL VARIABLES ===
# Use simple arrays for bash 3.2 compatibility
TIMESTAMPS=""
TOKENS=""
INPUT_TOKENS=""
OUTPUT_TOKENS=""
DELTAS=""
DELTA_TIMES=""
DATA_COUNT=0
TERM_WIDTH=80
TERM_HEIGHT=24
GRAPH_WIDTH=60
GRAPH_HEIGHT=15
SESSION_ID=""
GRAPH_TYPE="delta"
COLOR_ENABLED=true
TOKEN_DETAIL_ENABLED=true
WATCH_MODE=true
WATCH_INTERVAL=2
REDUCED_MOTION=false
CYCLE_COUNTER=0

# === UTILITY FUNCTIONS ===

show_help() {
    cat <<'EOF'
Context Stats Visualizer for Claude Code

USAGE:
    context-stats.sh [session_id] [options]

ARGUMENTS:
    session_id    Optional session ID. If not provided, uses the latest session.

OPTIONS:
    --type <type>  Graph type to display:
                   - delta: Context growth per interaction (default)
                   - cumulative: Total context usage over time
                   - io: Input/output tokens over time
                   - both: Show cumulative and delta graphs
                   - all: Show all graphs including I/O
    -w [interval]  Set refresh interval in seconds (default: 2)
    --no-watch     Show graphs once and exit (disable live monitoring)
    --no-color     Disable color output
    --help         Show this help message

NOTE:
    By default, context-stats runs in live monitoring mode, refreshing every 2 seconds.
    Press Ctrl+C to exit. Use --no-watch to display graphs once and exit.

EXAMPLES:
    # Live monitoring (default, refreshes every 2s)
    context-stats.sh

    # Live monitoring with custom interval
    context-stats.sh -w 5

    # Show graphs once and exit
    context-stats.sh --no-watch

    # Show graphs for specific session
    context-stats.sh abc123def

    # Show cumulative graph instead of delta
    context-stats.sh --type cumulative

    # Combine options
    context-stats.sh abc123 --type cumulative -w 3

    # Output to file (no colors, single run)
    context-stats.sh --no-watch --no-color > output.txt

DATA SOURCE:
    Reads token history from ~/.claude/statusline/statusline.<session_id>.state

EOF
}

error_exit() {
    echo -e "${RED}Error:${RESET} $1" >&2
    exit "${2:-1}"
}

warn() {
    echo -e "${YELLOW}Warning:${RESET} $1" >&2
}

info() {
    echo -e "${DIM}$1${RESET}"
}

show_waiting_message() {
    local session_id=$1
    local message=${2:-"Waiting for session data..."}

    echo ""
    if [ -n "$session_id" ]; then
        echo -e "${BOLD}${MAGENTA}Context Stats${RESET} ${DIM}(Session: $session_id)${RESET}"
    else
        echo -e "${BOLD}${MAGENTA}Context Stats${RESET}"
    fi
    echo ""
    echo -e "  ${CYAN}⏳ ${message}${RESET}"
    echo ""
    echo -e "  ${DIM}The session has just started and no data has been recorded yet.${RESET}"
    echo -e "  ${DIM}Data will appear after the first Claude interaction.${RESET}"
    echo ""
}

init_colors() {
    if [ "$COLOR_ENABLED" != "true" ] || [ "${NO_COLOR:-}" = "1" ] || [ ! -t 1 ]; then
        # shellcheck disable=SC2034
        BLUE='' # Kept for consistency with other color definitions
        MAGENTA=''
        CYAN=''
        GREEN=''
        YELLOW=''
        RED=''
        BOLD=''
        DIM=''
        RESET=''
    fi
}

get_terminal_dimensions() {
    # Try tput first
    if command -v tput >/dev/null 2>&1; then
        TERM_WIDTH=$(tput cols 2>/dev/null || echo 80)
        TERM_HEIGHT=$(tput lines 2>/dev/null || echo 24)
    else
        # Fallback to stty
        local dims
        dims=$(stty size 2>/dev/null || echo "24 80")
        TERM_HEIGHT=$(echo "$dims" | cut -d' ' -f1)
        TERM_WIDTH=$(echo "$dims" | cut -d' ' -f2)
    fi

    # Calculate graph dimensions
    GRAPH_WIDTH=$((TERM_WIDTH - 15))  # Reserve space for Y-axis labels
    GRAPH_HEIGHT=$((TERM_HEIGHT / 3)) # Each graph takes 1/3 of terminal

    # Enforce minimums and maximums
    [ $GRAPH_WIDTH -lt 30 ] && GRAPH_WIDTH=30
    [ $GRAPH_HEIGHT -lt 8 ] && GRAPH_HEIGHT=8
    [ $GRAPH_HEIGHT -gt 20 ] && GRAPH_HEIGHT=20
}

format_number() {
    local num=$1
    if [ "$TOKEN_DETAIL_ENABLED" = "true" ]; then
        # Comma-separated format
        echo "$num" | awk '{ printf "%\047d", $1 }' 2>/dev/null || echo "$num"
    else
        # Abbreviated format
        echo "$num" | awk '{
            if ($1 >= 1000000) printf "%.1fM", $1/1000000
            else if ($1 >= 1000) printf "%.1fk", $1/1000
            else printf "%d", $1
        }'
    fi
}

format_timestamp() {
    local ts=$1
    # Try BSD date first (macOS), then GNU date
    date -r "$ts" +%H:%M 2>/dev/null || date -d "@$ts" +%H:%M 2>/dev/null || echo "$ts"
}

format_duration() {
    local seconds=$1
    local hours=$((seconds / 3600))
    local minutes=$(((seconds % 3600) / 60))

    if [ $hours -gt 0 ]; then
        echo "${hours}h ${minutes}m"
    elif [ $minutes -gt 0 ]; then
        echo "${minutes}m"
    else
        echo "${seconds}s"
    fi
}

# === ACTIVITY ICONS & WAITING TEXT ===

# Waiting messages for rotating display
WAITING_MESSAGES="Thinking... Cooking... Crunching_tokens... Compiling_plan... Running_steps... Processing... Working_on_it... Analyzing..."
WAITING_MSG_COUNT=8

get_waiting_text() {
    local cycle=$1
    if [ "$REDUCED_MOTION" = "true" ]; then
        echo "Working..."
        return
    fi
    # Rotate every 2 cycles
    local msg_idx=$(( (cycle / 2) % WAITING_MSG_COUNT + 1 ))
    local msg
    msg=$(echo "$WAITING_MESSAGES" | awk -v n="$msg_idx" '{ print $n }')
    # Replace underscores with spaces
    echo "$msg" | tr '_' ' '
}

# Check if session is active (last entry within timeout seconds)
is_session_active() {
    local last_ts=$1
    local timeout=${2:-30}
    local now
    now=$(date +%s)
    local diff=$((now - last_ts))
    [ "$diff" -le "$timeout" ]
}

# Detect spike: latest delta > 15% of context window OR > 3x rolling avg of previous deltas
detect_spike() {
    local deltas_str=$1
    local context_window=$2
    local window=${3:-5}

    local count
    count=$(echo "$deltas_str" | wc -w | tr -d ' ')
    [ "$count" -eq 0 ] && return 1

    local latest
    latest=$(echo "$deltas_str" | awk '{ print $NF }')

    # Absolute threshold: > 15% of context window
    if [ "$context_window" -gt 0 ]; then
        local threshold=$((context_window * 15 / 100))
        [ "$latest" -gt "$threshold" ] && return 0
    fi

    # Relative threshold: > 3x rolling avg of previous deltas
    if [ "$count" -ge 2 ]; then
        # Get previous deltas (exclude last)
        local prev_count=$((count - 1))
        local start=$((prev_count > window ? count - window - 1 : 0))
        local prev_sum=0
        local prev_n=0
        local idx=0
        for d in $deltas_str; do
            if [ "$idx" -ge "$start" ] && [ "$idx" -lt "$prev_count" ]; then
                prev_sum=$((prev_sum + d))
                prev_n=$((prev_n + 1))
            fi
            idx=$((idx + 1))
        done
        if [ "$prev_n" -gt 0 ]; then
            local avg=$((prev_sum / prev_n))
            if [ "$avg" -gt 0 ] && [ "$latest" -gt $((avg * 3)) ]; then
                return 0
            fi
        fi
    fi

    return 1
}

# Determine activity tier: idle, low, medium, high, spike
get_activity_tier() {
    local last_ts=$1
    local context_window=$2
    local deltas_str=$3

    # Check if idle (>30s since last entry)
    if ! is_session_active "$last_ts"; then
        echo "idle"
        return
    fi

    local count
    count=$(echo "$deltas_str" | wc -w | tr -d ' ')
    if [ "$count" -eq 0 ]; then
        echo "idle"
        return
    fi

    local latest
    latest=$(echo "$deltas_str" | awk '{ print $NF }')

    if [ "$latest" -le 0 ]; then
        echo "idle"
        return
    fi

    # Check spike first
    if detect_spike "$deltas_str" "$context_window"; then
        echo "spike"
        return
    fi

    if [ "$context_window" -le 0 ]; then
        echo "low"
        return
    fi

    # Delta as percentage of context window (x100 for integer math)
    local delta_pct_x100=$((latest * 10000 / context_window))

    if [ "$delta_pct_x100" -gt 500 ]; then
        echo "high"
    elif [ "$delta_pct_x100" -gt 200 ]; then
        echo "medium"
    else
        echo "low"
    fi
}

# Get text label for tier
get_tier_label() {
    local tier=$1
    case "$tier" in
        idle)   echo "Idle" ;;
        low)    echo "Low activity" ;;
        medium) echo "Active" ;;
        high)   echo "High activity" ;;
        spike)  echo "Spike!" ;;
        *)      echo "Idle" ;;
    esac
}

# === DATA FUNCTIONS ===

migrate_old_state_files() {
    local old_dir=~/.claude
    local new_file
    mkdir -p "$STATE_DIR"
    for old_file in "$old_dir"/statusline*.state; do
        if [ -f "$old_file" ]; then
            new_file="${STATE_DIR}/$(basename "$old_file")"
            if [ ! -f "$new_file" ]; then
                mv "$old_file" "$new_file" 2>/dev/null || true
            else
                rm -f "$old_file" 2>/dev/null || true
            fi
        fi
    done
}

find_latest_state_file() {
    migrate_old_state_files

    if [ -n "$SESSION_ID" ]; then
        # Specific session requested - return path even if file doesn't exist yet
        local file="$STATE_DIR/statusline.${SESSION_ID}.state"
        echo "$file"
        return 0
    fi

    # Find most recent state file
    local latest
    latest=$(find "$STATE_DIR" -maxdepth 1 -name 'statusline.*.state' -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)

    if [ -z "$latest" ]; then
        # Try the default state file
        if [ -f "$STATE_DIR/statusline.state" ]; then
            echo "$STATE_DIR/statusline.state"
            return 0
        fi
        # Return empty - no state files found
        return 1
    fi

    echo "$latest"
}

validate_state_file() {
    local file=$1

    if [ ! -f "$file" ]; then
        error_exit "State file not found: $file"
    fi

    if [ ! -r "$file" ]; then
        error_exit "Cannot read state file: $file"
    fi

    local line_count
    line_count=$(wc -l <"$file" | tr -d ' ')

    if [ "$line_count" -lt 2 ]; then
        error_exit "Need at least 2 data points to generate graphs.\nFound: $line_count entry. Use Claude Code to accumulate more data."
    fi
}

load_token_history() {
    local file=$1
    local line_num=0
    local valid_lines=0
    local skipped_lines=0

    TIMESTAMPS=""
    TOKENS=""
    INPUT_TOKENS=""
    OUTPUT_TOKENS=""
    CONTEXT_SIZES=""
    CURRENT_USED_TOKENS=""
    CURRENT_INPUT_TOKENS=""
    CURRENT_OUTPUT_TOKENS=""
    LAST_MODEL_ID=""
    LAST_PROJECT_DIR=""
    LAST_COST_USD=""
    LAST_LINES_ADDED=""
    LAST_LINES_REMOVED=""
    DATA_COUNT=0

    while IFS=',' read -r ts total_in total_out cur_in cur_out cache_creation cache_read cost_usd lines_added lines_removed session_id model_id workspace_project_dir context_size rest || [ -n "$ts" ]; do
        line_num=$((line_num + 1))

        # Skip empty lines
        [ -z "$ts" ] && continue

        # Validate timestamp (simple numeric check)
        case "$ts" in
        '' | *[!0-9]*)
            skipped_lines=$((skipped_lines + 1))
            [ $skipped_lines -le 3 ] && warn "Skipping invalid line $line_num"
            continue
            ;;
        esac

        # Handle both old format (timestamp,tokens) and new format (timestamp,total_in,total_out,...)
        if [ -z "$total_out" ]; then
            # Old format: timestamp,tokens - use tokens as both input and output combined
            local tok="$total_in"
            case "$tok" in
            '' | *[!0-9]*)
                skipped_lines=$((skipped_lines + 1))
                continue
                ;;
            esac
            total_in=$tok
            total_out=0
        fi

        # Validate numeric fields
        case "$total_in" in
        '' | *[!0-9]*) total_in=0 ;;
        esac
        case "$total_out" in
        '' | *[!0-9]*) total_out=0 ;;
        esac
        case "$cur_in" in
        '' | *[!0-9]*) cur_in=0 ;;
        esac
        case "$cache_creation" in
        '' | *[!0-9]*) cache_creation=0 ;;
        esac
        case "$cache_read" in
        '' | *[!0-9]*) cache_read=0 ;;
        esac

        # Calculate combined tokens for backward compatibility
        local combined=$((total_in + total_out))

        # Calculate current context usage (what's actually in the context window)
        local current_used=$((cur_in + cache_creation + cache_read))

        # Validate context size (new format)
        case "$context_size" in
        '' | *[!0-9]*) context_size=0 ;;
        esac

        # Append to space-separated strings (bash 3.2 compatible)
        if [ -z "$TIMESTAMPS" ]; then
            TIMESTAMPS="$ts"
            TOKENS="$combined"
            INPUT_TOKENS="$total_in"
            OUTPUT_TOKENS="$total_out"
            CONTEXT_SIZES="$context_size"
            CURRENT_USED_TOKENS="$current_used"
            CURRENT_INPUT_TOKENS="$cur_in"
            CURRENT_OUTPUT_TOKENS="$cur_out"
        else
            TIMESTAMPS="$TIMESTAMPS $ts"
            TOKENS="$TOKENS $combined"
            INPUT_TOKENS="$INPUT_TOKENS $total_in"
            OUTPUT_TOKENS="$OUTPUT_TOKENS $total_out"
            CONTEXT_SIZES="$CONTEXT_SIZES $context_size"
            CURRENT_USED_TOKENS="$CURRENT_USED_TOKENS $current_used"
            CURRENT_INPUT_TOKENS="$CURRENT_INPUT_TOKENS $cur_in"
            CURRENT_OUTPUT_TOKENS="$CURRENT_OUTPUT_TOKENS $cur_out"
        fi
        # Store last values (will be kept)
        LAST_MODEL_ID="$model_id"
        LAST_PROJECT_DIR="$workspace_project_dir"
        LAST_COST_USD="$cost_usd"
        LAST_LINES_ADDED="$lines_added"
        LAST_LINES_REMOVED="$lines_removed"
        valid_lines=$((valid_lines + 1))
    done <"$file"

    DATA_COUNT=$valid_lines

    if [ $skipped_lines -gt 3 ]; then
        warn "... and $((skipped_lines - 3)) more invalid lines"
    fi

    if [ $valid_lines -lt 2 ]; then
        error_exit "Loaded only $valid_lines valid data points. Need at least 2."
    fi

    # Only show info message in non-watch mode
    if [ "$WATCH_MODE" != "true" ]; then
        info "Loaded $valid_lines data points from $(basename "$file")"
    fi
}

calculate_deltas() {
    local prev_tok=""
    local idx=0
    DELTAS=""
    DELTA_TIMES=""

    # Use CURRENT_USED_TOKENS (actual context usage) for delta calculation
    for tok in $CURRENT_USED_TOKENS; do
        idx=$((idx + 1))
        if [ -z "$prev_tok" ]; then
            # Skip first data point - no previous value to compare against
            prev_tok=$tok
            continue
        fi

        local delta=$((tok - prev_tok))
        # Handle negative deltas (session reset) by showing 0
        [ $delta -lt 0 ] && delta=0

        # Get corresponding timestamp for this delta
        local ts
        ts=$(get_element "$TIMESTAMPS" "$idx")

        if [ -z "$DELTAS" ]; then
            DELTAS="$delta"
            DELTA_TIMES="$ts"
        else
            DELTAS="$DELTAS $delta"
            DELTA_TIMES="$DELTA_TIMES $ts"
        fi
        prev_tok=$tok
    done
}

# Get Nth element from space-separated string (1-indexed)
get_element() {
    local str=$1
    local idx=$2
    echo "$str" | awk -v n="$idx" '{ print $n }'
}

# Get min/max/avg from space-separated numbers
get_stats() {
    local data=$1
    echo "$data" | tr ' ' '\n' | awk '
        BEGIN { min=999999999999; max=0; sum=0; n=0 }
        {
            if ($1 < min) min = $1
            if ($1 > max) max = $1
            sum += $1
            n++
        }
        END {
            avg = (n > 0) ? int(sum/n) : 0
            print min, max, avg, sum, n
        }
    '
}

# === GRAPH RENDERING ===

render_timeseries_graph() {
    local title=$1
    local data=$2
    local times=$3
    local color=$4

    local n
    n=$(echo "$data" | wc -w | tr -d ' ')
    [ "$n" -eq 0 ] && return

    # Get min/max
    local stats
    stats=$(get_stats "$data")
    local min max
    min=$(echo "$stats" | cut -d' ' -f1)
    max=$(echo "$stats" | cut -d' ' -f2)
    # avg is available but not used in graph rendering

    # Avoid division by zero
    [ "$min" -eq "$max" ] && max=$((min + 1))
    local range=$((max - min))

    # Print title
    echo ""
    echo -e "${BOLD}$title${RESET}"
    echo -e "${DIM}Max: $(format_number "$max")  Min: $(format_number "$min")  Points: $n${RESET}"
    echo ""

    # Build grid using awk - smooth line with filled area below
    local grid_output
    grid_output=$(echo "$data" | awk -v width="$GRAPH_WIDTH" -v height="$GRAPH_HEIGHT" \
        -v min="$min" -v max="$max" -v range="$range" '
    BEGIN {
        # Characters for different parts of the graph
        # Line: dots for the trend line
        # Fill: lighter shading below the line
        dot = "●"
        fill_dark = "░"
        fill_light = "▒"
        empty = " "

        # Initialize grid with empty spaces
        for (r = 0; r < height; r++) {
            for (c = 0; c < width; c++) {
                grid[r,c] = empty
            }
        }

        # Store y values for each x position (for interpolation)
        for (c = 0; c < width; c++) {
            line_y[c] = -1
        }
    }
    {
        n = NF

        # First pass: calculate y position for each data point
        for (i = 1; i <= n; i++) {
            val = $i

            # Map index to x coordinate
            if (n == 1) {
                x = int(width / 2)
            } else {
                x = int((i - 1) * (width - 1) / (n - 1))
            }
            if (x >= width) x = width - 1
            if (x < 0) x = 0

            # Map value to y coordinate (inverted: 0=top)
            y = (max - val) * (height - 1) / range
            if (y >= height) y = height - 1
            if (y < 0) y = 0

            data_x[i] = x
            data_y[i] = y
        }

        # Second pass: interpolate between points to fill every x position
        for (i = 1; i < n; i++) {
            x1 = data_x[i]
            y1 = data_y[i]
            x2 = data_x[i+1]
            y2 = data_y[i+1]

            # Linear interpolation for each x between x1 and x2
            for (x = x1; x <= x2; x++) {
                if (x2 == x1) {
                    y = y1
                } else {
                    # Linear interpolation
                    t = (x - x1) / (x2 - x1)
                    y = y1 + t * (y2 - y1)
                }
                line_y[x] = y
            }
        }

        # Third pass: draw the filled area and line
        for (c = 0; c < width; c++) {
            if (line_y[c] >= 0) {
                line_row = int(line_y[c] + 0.5)  # Round to nearest integer
                if (line_row >= height) line_row = height - 1
                if (line_row < 0) line_row = 0

                # Fill area below the line with gradient
                for (r = line_row; r < height; r++) {
                    if (r == line_row) {
                        grid[r, c] = dot  # The line itself
                    } else if (r < line_row + 2) {
                        grid[r, c] = fill_light  # Darker fill near line
                    } else {
                        grid[r, c] = fill_dark   # Lighter fill further down
                    }
                }
            }
        }

        # Fourth pass: mark actual data points with larger dots
        for (i = 1; i <= n; i++) {
            x = data_x[i]
            y = int(data_y[i] + 0.5)
            if (y >= height) y = height - 1
            if (y < 0) y = 0
            grid[y, x] = dot
        }
    }
    END {
        # Print grid
        for (r = 0; r < height; r++) {
            row = ""
            for (c = 0; c < width; c++) {
                row = row grid[r,c]
            }
            print row
        }
    }')

    # Print grid with Y-axis labels
    local r=0
    while [ $r -lt $GRAPH_HEIGHT ]; do
        local val=$((max - r * range / (GRAPH_HEIGHT - 1)))
        local label=""

        # Show labels at top, middle, and bottom
        if [ $r -eq 0 ] || [ $r -eq $((GRAPH_HEIGHT / 2)) ] || [ $r -eq $((GRAPH_HEIGHT - 1)) ]; then
            label=$(format_number $val)
        fi

        local row
        row=$(echo "$grid_output" | sed -n "$((r + 1))p")
        printf '%10s %b│%b%b%s%b\n' "$label" "${DIM}" "${RESET}" "${color}" "$row" "${RESET}"
        r=$((r + 1))
    done

    # X-axis
    printf '%10s %b└' "" "${DIM}"
    local c=0
    while [ $c -lt $GRAPH_WIDTH ]; do
        printf "─"
        c=$((c + 1))
    done
    printf '%b\n' "${RESET}"

    # Time labels
    local first_time last_time mid_time
    first_time=$(format_timestamp "$(get_element "$times" 1)")
    last_time=$(format_timestamp "$(get_element "$times" "$n")")
    local mid_idx=$(((n + 1) / 2))
    mid_time=$(format_timestamp "$(get_element "$times" "$mid_idx")")

    printf '%11s%b%-*s%s%*s%b\n' "" "${DIM}" "$((GRAPH_WIDTH / 3))" "$first_time" "$mid_time" "$((GRAPH_WIDTH / 3))" "$last_time" "${RESET}"
}

render_summary() {
    local first_ts last_ts duration current_tokens total_growth
    first_ts=$(get_element "$TIMESTAMPS" 1)
    last_ts=$(get_element "$TIMESTAMPS" "$DATA_COUNT")
    duration=$((last_ts - first_ts))
    current_tokens=$(get_element "$TOKENS" "$DATA_COUNT")
    local first_tokens
    first_tokens=$(get_element "$TOKENS" 1)
    total_growth=$((current_tokens - first_tokens))

    # Get I/O token stats (current request tokens for display)
    local current_input current_output
    current_input=$(get_element "$CURRENT_INPUT_TOKENS" "$DATA_COUNT")
    current_output=$(get_element "$CURRENT_OUTPUT_TOKENS" "$DATA_COUNT")
    current_context=$(get_element "$CONTEXT_SIZES" "$DATA_COUNT")

    # Get actual context window usage (current_input + cache_creation + cache_read)
    local current_used
    current_used=$(get_element "$CURRENT_USED_TOKENS" "$DATA_COUNT")

    # Calculate remaining context window
    local remaining_context=$((current_context - current_used))
    local context_percentage=0
    if [ "$current_context" -gt 0 ]; then
        context_percentage=$((remaining_context * 100 / current_context))
    fi

    # Get statistics
    local del_stats
    del_stats=$(get_stats "$DELTAS")
    local del_max del_avg
    del_max=$(echo "$del_stats" | cut -d' ' -f2)
    del_avg=$(echo "$del_stats" | cut -d' ' -f3)

    echo ""
    echo -e "${BOLD}Session Summary${RESET}"
    local line_width=$((GRAPH_WIDTH + 11))
    printf '%b' "${DIM}"
    local i=0
    while [ $i -lt $line_width ]; do
        printf "-"
        i=$((i + 1))
    done
    printf '%b\n' "${RESET}"

    # Determine status zone based on context usage
    if [ "$current_context" -gt 0 ]; then
        local usage_percentage=$((100 - context_percentage))
        local status_color status_text status_hint
        if [ "$usage_percentage" -lt 40 ]; then
            status_color="${GREEN}"
            status_text="SMART ZONE"
            status_hint="You are in the smart zone"
        elif [ "$usage_percentage" -lt 80 ]; then
            status_color="${YELLOW}"
            status_text="DUMB ZONE"
            status_hint="You are in the dumb zone - Dex Horthy says so"
        else
            status_color="${RED}"
            status_text="WRAP UP ZONE"
            status_hint="Better to wrap up and start a new session"
        fi
        # Context remaining (before status)
        printf '  %b%-20s%b %s/%s (%s%%)\n' "${status_color}" "Context Remaining:" "${RESET}" "$(format_number "$remaining_context")" "$(format_number "$current_context")" "$context_percentage"
        # Status indicator
        printf '  %b%b>>> %s <<<%b %b(%s)%b\n' "${status_color}" "${BOLD}" "$status_text" "${RESET}" "${DIM}" "$status_hint" "${RESET}"
        echo ""
    fi
    # Session details (ordered: Last Growth, I/O, Lines, Cost, Model, Duration)
    if [ -n "$DELTAS" ]; then
        local delta_count last_growth
        delta_count=$(echo "$DELTAS" | wc -w | tr -d ' ')
        last_growth=$(get_element "$DELTAS" "$delta_count")
        if [ -n "$last_growth" ] && [ "$last_growth" -gt 0 ] 2>/dev/null; then
            printf '  %b%-20s%b +%s\n' "${CYAN}" "Last Growth:" "${RESET}" "$(format_number "$last_growth")"
        fi
    fi
    printf '  %b%-20s%b %s\n' "${BLUE}" "Input Tokens:" "${RESET}" "$(format_number "$current_input")"
    printf '  %b%-20s%b %s\n' "${MAGENTA}" "Output Tokens:" "${RESET}" "$(format_number "$current_output")"
    if [ -n "$LAST_LINES_ADDED" ] && [ "$LAST_LINES_ADDED" != "0" ] || [ -n "$LAST_LINES_REMOVED" ] && [ "$LAST_LINES_REMOVED" != "0" ]; then
        printf '  %b%-20s%b %b+%s%b / %b-%s%b\n' "${DIM}" "Lines Changed:" "${RESET}" "${GREEN}" "$(format_number "$LAST_LINES_ADDED")" "${RESET}" "${RED}" "$(format_number "$LAST_LINES_REMOVED")" "${RESET}"
    fi
    if [ -n "$LAST_COST_USD" ] && [ "$LAST_COST_USD" != "0" ]; then
        printf '  %b%-20s%b $%s\n' "${YELLOW}" "Total Cost:" "${RESET}" "$LAST_COST_USD"
    fi
    if [ -n "$LAST_MODEL_ID" ]; then
        printf '  %b%-20s%b %s\n' "${DIM}" "Model:" "${RESET}" "$LAST_MODEL_ID"
    fi
    printf '  %b%-20s%b %s\n' "${CYAN}" "Session Duration:" "${RESET}" "$(format_duration "$duration")"
    echo ""
}

render_footer() {
    echo -e "${DIM}Powered by ${CYAN}cc-context-stats${DIM} v${VERSION}-${COMMIT_HASH} - https://github.com/luongnv89/cc-context-stats${RESET}"
    echo ""
}

# === ARGUMENT PARSING ===

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
        --help | -h)
            show_help
            exit 0
            ;;
        --no-color)
            COLOR_ENABLED=false
            shift
            ;;
        --no-watch)
            WATCH_MODE=false
            shift
            ;;
        -w)
            # Set refresh interval
            if [ $# -ge 2 ] && [[ "$2" =~ ^[0-9]+$ ]]; then
                WATCH_INTERVAL="$2"
                shift 2
            else
                shift
            fi
            ;;
        --type)
            if [ $# -lt 2 ]; then
                error_exit "--type requires an argument: cumulative, delta, or both"
            fi
            case "$2" in
            cumulative | delta | io | both | all)
                GRAPH_TYPE="$2"
                ;;
            *)
                error_exit "Invalid graph type: $2. Use: cumulative, delta, io, both, or all"
                ;;
            esac
            shift 2
            ;;
        --*)
            error_exit "Unknown option: $1\nUse --help for usage information."
            ;;
        *)
            # Assume it's a session ID
            if [ -z "$SESSION_ID" ]; then
                SESSION_ID="$1"
            else
                error_exit "Unexpected argument: $1"
            fi
            shift
            ;;
        esac
    done
}

# === MAIN ===

# Load configuration from file
load_config() {
    if [ -f "$CONFIG_FILE" ]; then
        while IFS='=' read -r key value || [ -n "$key" ]; do
            # Skip comments and empty lines
            case "$key" in
            '#'* | '') continue ;;
            esac

            # Sanitize key and value
            key=$(echo "$key" | tr -d '[:space:]')
            value=$(echo "$value" | tr -d '"' | tr -d "'" | tr -d '[:space:]')

            case "$key" in
            token_detail)
                if [ "$value" = "false" ]; then
                    TOKEN_DETAIL_ENABLED=false
                fi
                ;;
            reduced_motion)
                if [ "$value" = "true" ]; then
                    REDUCED_MOTION=true
                fi
                ;;
            esac
        done <"$CONFIG_FILE"
    fi
}

# Render graphs once
render_once() {
    local state_file=$1

    # Load data
    load_token_history "$state_file"
    calculate_deltas

    # Display header
    local session_name project_name
    session_name=$(basename "$state_file" .state | sed 's/statusline\.//')
    # Extract project name from path (last component)
    if [ -n "$LAST_PROJECT_DIR" ]; then
        project_name=$(basename "$LAST_PROJECT_DIR")
    fi
    echo ""
    if [ -n "$project_name" ]; then
        echo -e "${BOLD}${MAGENTA}Context Stats${RESET} ${DIM}(${CYAN}$project_name${DIM} • $session_name)${RESET}"
    else
        echo -e "${BOLD}${MAGENTA}Context Stats${RESET} ${DIM}(Session: $session_name)${RESET}"
    fi

    # Activity indicator (waiting text + label)
    local last_ts
    last_ts=$(get_element "$TIMESTAMPS" "$DATA_COUNT")
    local last_context
    last_context=$(get_element "$CONTEXT_SIZES" "$DATA_COUNT")
    [ -z "$last_context" ] && last_context=0

    local tier
    tier=$(get_activity_tier "$last_ts" "$last_context" "$DELTAS")
    local label
    label=$(get_tier_label "$tier")

    if is_session_active "$last_ts"; then
        local wait_text
        wait_text=$(get_waiting_text "$CYCLE_COUNTER")
        echo -e "  ${DIM}${wait_text} [${label}]${RESET}"
    else
        echo -e "  ${DIM}${label}${RESET}"
    fi

    # Render graphs (use CURRENT_USED_TOKENS for actual context window usage)
    case "$GRAPH_TYPE" in
    cumulative)
        render_timeseries_graph "Context Usage Over Time" "$CURRENT_USED_TOKENS" "$TIMESTAMPS" "$GREEN"
        ;;
    delta)
        render_timeseries_graph "Context Growth Per Interaction" "$DELTAS" "$DELTA_TIMES" "$CYAN"
        ;;
    io)
        render_timeseries_graph "Input Tokens (per request)" "$CURRENT_INPUT_TOKENS" "$TIMESTAMPS" "$BLUE"
        render_timeseries_graph "Output Tokens (per request)" "$CURRENT_OUTPUT_TOKENS" "$TIMESTAMPS" "$MAGENTA"
        ;;
    both)
        render_timeseries_graph "Context Usage Over Time" "$CURRENT_USED_TOKENS" "$TIMESTAMPS" "$GREEN"
        render_timeseries_graph "Context Growth Per Interaction" "$DELTAS" "$DELTA_TIMES" "$CYAN"
        ;;
    all)
        render_timeseries_graph "Input Tokens (per request)" "$CURRENT_INPUT_TOKENS" "$TIMESTAMPS" "$BLUE"
        render_timeseries_graph "Output Tokens (per request)" "$CURRENT_OUTPUT_TOKENS" "$TIMESTAMPS" "$MAGENTA"
        render_timeseries_graph "Context Usage Over Time" "$CURRENT_USED_TOKENS" "$TIMESTAMPS" "$GREEN"
        render_timeseries_graph "Context Growth Per Interaction" "$DELTAS" "$DELTA_TIMES" "$CYAN"
        ;;
    esac

    # Render summary
    render_summary

    # Render footer
    render_footer
}

# Watch mode - continuously refresh the display
run_watch_mode() {
    local state_file=$1

    # ANSI escape codes for cursor control (using $'...' for proper interpretation)
    local CURSOR_HOME=$'\033[H'
    local CLEAR_SCREEN=$'\033[2J'
    local HIDE_CURSOR=$'\033[?25l'
    local SHOW_CURSOR=$'\033[?25h'
    local CLEAR_TO_END=$'\033[J'

    # Set up signal handler for clean exit
    trap 'printf "%s\n" "${SHOW_CURSOR}"; echo -e "${DIM}Watch mode stopped.${RESET}"; exit 0' INT TERM

    # Hide cursor for cleaner display
    printf "%s" "${HIDE_CURSOR}"

    # Initial clear
    printf "%s%s" "${CLEAR_SCREEN}" "${CURSOR_HOME}"

    while true; do
        # Re-read terminal dimensions in case of resize
        get_terminal_dimensions

        # Capture all output into a variable for atomic write
        local output
        output=$(
            # Show watch mode indicator with live timestamp
            local current_time
            current_time=$(date +%H:%M:%S)
            echo -e "${DIM}[LIVE ${current_time}] Refresh: ${WATCH_INTERVAL}s | Ctrl+C to exit${RESET}"

            # Handle case where state_file is empty (no sessions found at all)
            if [ -z "$state_file" ]; then
                local wait_msg
                wait_msg=$(get_waiting_text "$CYCLE_COUNTER")
                show_waiting_message "" "$wait_msg"
            # Re-validate and render (file might have new data)
            elif [ -f "$state_file" ]; then
                local line_count
                line_count=$(wc -l <"$state_file" | tr -d ' ')
                if [ "$line_count" -ge 2 ]; then
                    render_once "$state_file"
                else
                    show_waiting_message "$SESSION_ID" "Waiting for more data points..."
                    echo -e "  ${DIM}Current: ${line_count} point(s), need at least 2${RESET}"
                fi
            else
                # File doesn't exist yet (new session)
                show_waiting_message "$SESSION_ID" "Waiting for session data..."
            fi
        )

        # Atomic write: CURSOR_HOME + content + CLEAR_TO_END (clean up stale trailing lines)
        printf "%s%s\n%s" "${CURSOR_HOME}" "$output" "${CLEAR_TO_END}"

        CYCLE_COUNTER=$((CYCLE_COUNTER + 1))
        sleep "$WATCH_INTERVAL"
    done
}

main() {
    parse_args "$@"
    init_colors
    get_terminal_dimensions
    load_config

    # Find state file
    local state_file
    if ! state_file=$(find_latest_state_file); then
        # No state files found at all
        if [ "$WATCH_MODE" = "true" ]; then
            # Watch mode - wait for data
            run_watch_mode ""
        else
            # Single run mode - show friendly message
            echo -e "${YELLOW}No session data found.${RESET}"
            echo -e "${DIM}Run Claude Code to generate token usage data.${RESET}"
            exit 0
        fi
        return
    fi

    if [ "$WATCH_MODE" = "true" ]; then
        # Watch mode - don't exit on validation errors, keep trying
        run_watch_mode "$state_file"
    else
        # Single run mode - check if file exists
        if [ ! -f "$state_file" ]; then
            # Specific session requested but file doesn't exist yet
            show_waiting_message "$SESSION_ID"
            exit 0
        fi
        validate_state_file "$state_file"
        render_once "$state_file"
    fi
}

main "$@"
