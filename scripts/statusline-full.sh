#!/bin/bash
# Full-featured status line with context window usage
# Usage: Copy to ~/.claude/statusline.sh and make executable
#
# Configuration:
# Create/edit ~/.claude/statusline.conf and set:
#
#   autocompact=true   (when autocompact is enabled in Claude Code - default)
#   autocompact=false  (when you disable autocompact via /config in Claude Code)
#
#   token_detail=true  (show exact token count like 64,000 - default)
#   token_detail=false (show abbreviated tokens like 64.0k)
#
#   show_delta=true    (show token delta since last refresh like [+2,500] - default)
#   show_delta=false   (disable delta display - saves file I/O on every refresh)
#
#   show_session=true  (show session_id in status line - default)
#   show_session=false (hide session_id from status line)
#
# When AC is enabled, 22.5% of context window is reserved for autocompact buffer.
#
# State file format (CSV):
#   timestamp,total_input_tokens,total_output_tokens,current_usage_input_tokens,current_usage_output_tokens,current_usage_cache_creation,current_usage_cache_read,total_cost_usd,total_lines_added,total_lines_removed,session_id,model_id,workspace_project_dir

# Colors (defaults, overridable via config)
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'

# Named colors for config parsing
declare -A COLOR_NAMES=(
    [black]='\033[0;30m' [red]='\033[0;31m' [green]='\033[0;32m'
    [yellow]='\033[0;33m' [blue]='\033[0;34m' [magenta]='\033[0;35m'
    [cyan]='\033[0;36m' [white]='\033[0;37m'
    [bright_black]='\033[0;90m' [bright_red]='\033[0;91m' [bright_green]='\033[0;92m'
    [bright_yellow]='\033[0;93m' [bright_blue]='\033[0;94m' [bright_magenta]='\033[0;95m'
    [bright_cyan]='\033[0;96m' [bright_white]='\033[0;97m'
)

# Color config key to slot mapping
declare -A COLOR_KEYS=(
    [color_green]=GREEN [color_yellow]=YELLOW [color_red]=RED
    [color_blue]=BLUE [color_magenta]=MAGENTA [color_cyan]=CYAN
)

# Parse a color name or #rrggbb hex into an ANSI escape code
parse_color() {
    local value
    value=$(echo "$1" | tr '[:upper:]' '[:lower:]' | xargs)
    if [[ -n "${COLOR_NAMES[$value]+x}" ]]; then
        echo "${COLOR_NAMES[$value]}"
        return
    fi
    if [[ "$value" =~ ^#[0-9a-f]{6}$ ]]; then
        local r=$((16#${value:1:2}))
        local g=$((16#${value:3:2}))
        local b=$((16#${value:5:2}))
        echo "\033[38;2;${r};${g};${b}m"
        return
    fi
}

# State file rotation constants
ROTATION_THRESHOLD=10000
ROTATION_KEEP=5000

# Rotate state file if it exceeds threshold
maybe_rotate_state_file() {
    local state_file="$1"
    [[ -f "$state_file" ]] || return
    local line_count
    line_count=$(wc -l < "$state_file" | tr -d ' ')
    if [[ "$line_count" -gt "$ROTATION_THRESHOLD" ]]; then
        local tmp_file="${state_file}.tmp.$$"
        tail -n "$ROTATION_KEEP" "$state_file" > "$tmp_file" && mv "$tmp_file" "$state_file" || rm -f "$tmp_file"
    fi
}

# Model Intelligence computation (uses awk for float math)
# MI(u) = max(0, 1 - u^beta) where beta is model-specific
compute_mi() {
    local used_tokens=$1 context_window=$2 model_id=$3 beta_override=$4
    awk -v used="$used_tokens" -v cw="$context_window" -v mid="$model_id" -v bo="$beta_override" '
    BEGIN {
        if (cw == 0) { printf "1.000"; exit }
        # Model profile lookup (beta only)
        mid_lower = tolower(mid)
        if (index(mid_lower, "opus") > 0)       beta = 1.8
        else if (index(mid_lower, "sonnet") > 0) beta = 1.5
        else if (index(mid_lower, "haiku") > 0)  beta = 1.2
        else                                      beta = 1.5
        # Beta override
        if (bo + 0 > 0) beta = bo + 0
        # MI calculation
        u = used / cw
        if (u <= 0) mi = 1.0
        else { mi = 1.0 - (u ^ beta); if (mi < 0) mi = 0.0 }
        printf "%.3f", mi
    }'
}

get_mi_color() {
    local mi_val="$1" utilization="$2"
    awk -v mi="$mi_val" -v u="$utilization" 'BEGIN {
        if (mi + 0 <= 0.80 || u + 0 >= 0.80) print "red"
        else if (mi + 0 < 0.90 || u + 0 >= 0.40) print "yellow"
        else print "green"
    }'
}

# Context zone indicator — always shown
# Returns "zone_word color_name" (e.g., "Plan green")
get_context_zone() {
    local used_tokens=$1 context_window=$2
    awk -v used="$used_tokens" -v cw="$context_window" '
    BEGIN {
        if (cw == 0) { print "Plan green"; exit }
        if (cw >= 500000) {
            # 1M model thresholds
            if (used < 70000)       print "Plan green"
            else if (used < 100000) print "Code yellow"
            else if (used < 250000) print "Dump orange"
            else if (used < 275000) print "ExDump dark_red"
            else                    print "Dead gray"
        } else {
            # Standard model thresholds
            dump_zone = int(cw * 0.40)
            warn_start = dump_zone - 30000
            if (warn_start < 0) warn_start = 0
            hard_limit = int(cw * 0.70)
            dead_zone = int(cw * 0.75)
            if (used < warn_start)       print "Plan green"
            else if (used < dump_zone)   print "Code yellow"
            else if (used < hard_limit)  print "Dump orange"
            else if (used < dead_zone)   print "ExDump dark_red"
            else                         print "Dead gray"
        }
    }'
}

zone_ansi_color() {
    local color_name="$1"
    case "$color_name" in
        green)    echo "$GREEN" ;;
        yellow)   echo "$YELLOW" ;;
        orange)   echo "\033[38;2;255;165;0m" ;;
        dark_red) echo "\033[38;2;139;0;0m" ;;
        gray)     echo "\033[0;90m" ;;
        *)        echo "$RESET" ;;
    esac
}

# Read JSON input from stdin
input=$(cat)

# Extract information from JSON
cwd=$(echo "$input" | jq -r '.workspace.current_dir')
project_dir=$(echo "$input" | jq -r '.workspace.project_dir')
model=$(echo "$input" | jq -r '.model.display_name // "Claude"')
session_id=$(echo "$input" | jq -r '.session_id // empty')
dir_name=$(basename "$cwd")

# Git information (skip optional locks for performance)
git_info=""
if [[ -d "$project_dir/.git" ]]; then
    git_branch=$(cd "$project_dir" 2>/dev/null && git --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null)
    git_status_count=$(cd "$project_dir" 2>/dev/null && git --no-optional-locks status --porcelain 2>/dev/null | wc -l | tr -d ' ')

    if [[ -n "$git_branch" ]]; then
        if [[ "$git_status_count" != "0" ]]; then
            git_info=" | ${MAGENTA}${git_branch}${RESET} ${CYAN}[${git_status_count}]${RESET}"
        else
            git_info=" | ${MAGENTA}${git_branch}${RESET}"
        fi
    fi
fi

# Read settings from ~/.claude/statusline.conf
# Sync this manually when you change settings in Claude Code via /config
autocompact_enabled=true
token_detail_enabled=true
show_delta_enabled=true
show_session_enabled=true
show_mi_enabled=false
mi_curve_beta=0
delta_info=""
mi_info=""
zone_info=""
session_info=""

# Create config file with defaults if it doesn't exist
if [[ ! -f ~/.claude/statusline.conf ]]; then
    mkdir -p ~/.claude
    cat >~/.claude/statusline.conf <<'EOF'
# Autocompact setting - sync with Claude Code's /config
autocompact=true

# Token display format
token_detail=true

# Show token delta since last refresh (adds file I/O on every refresh)
# Disable if you don't need it to reduce overhead
show_delta=true

# Show session_id in status line
show_session=true

# Model Intelligence (MI) score display
show_mi=false

# MI curve beta override (0 = use model-specific profile)
# mi_curve_beta=0
EOF
fi

if [[ -f ~/.claude/statusline.conf ]]; then
    while IFS= read -r line; do
        line=$(echo "$line" | xargs)
        [[ -z "$line" || "$line" == \#* ]] && continue
        [[ "$line" != *=* ]] && continue
        key="${line%%=*}"
        key=$(echo "$key" | xargs)
        raw_value="${line#*=}"
        raw_value=$(echo "$raw_value" | xargs)
        value_lower=$(echo "$raw_value" | tr '[:upper:]' '[:lower:]')
        case "$key" in
            autocompact)    [[ "$value_lower" == "false" ]] && autocompact_enabled=false ;;
            token_detail)   [[ "$value_lower" == "false" ]] && token_detail_enabled=false ;;
            show_delta)     [[ "$value_lower" == "false" ]] && show_delta_enabled=false ;;
            show_session)   [[ "$value_lower" == "false" ]] && show_session_enabled=false ;;
            show_mi)        [[ "$value_lower" == "false" ]] && show_mi_enabled=false ;;
            mi_curve_beta)  mi_curve_beta="$raw_value" ;;
            color_*)
                if [[ -n "${COLOR_KEYS[$key]+x}" ]]; then
                    slot="${COLOR_KEYS[$key]}"
                    ansi=$(parse_color "$raw_value")
                    if [[ -n "$ansi" ]]; then
                        eval "$slot='$ansi'"
                    fi
                fi
                ;;
        esac
    done < ~/.claude/statusline.conf
fi

# Width-fitting helpers
visible_width() {
    # Strip ANSI escape sequences (both literal \033 and actual ESC byte) and return string length
    local stripped
    stripped=$(printf '%s' "$1" | sed -e $'s/\033\[[0-9;]*m//g' -e 's/\\033\[[0-9;]*m//g')
    printf '%s' "$stripped" | wc -m | tr -d ' '
}

get_terminal_width() {
    # Return terminal width for fit_to_width truncation.
    # When running inside Claude Code's statusline subprocess, neither $COLUMNS
    # nor tput can detect the real terminal width (they always return 80).
    # If COLUMNS is explicitly set, trust it. Otherwise use 200 as default
    # so no parts are unnecessarily dropped; Claude Code handles overflow.
    if [[ -n "$COLUMNS" ]]; then
        echo "$COLUMNS"
    else
        local cols
        cols=$(tput cols 2>/dev/null || echo 80)
        if [[ "$cols" -eq 80 ]]; then
            echo 200
        else
            echo "$cols"
        fi
    fi
}

fit_to_width() {
    # Assemble parts into a single line that fits within max_width.
    # Usage: fit_to_width max_width part1 part2 part3 ...
    # First part (base) is always included. Subsequent parts are
    # included only if adding them does not exceed max_width.
    local max_width=$1
    shift
    local parts=("$@")

    if [[ ${#parts[@]} -eq 0 ]]; then
        echo ""
        return
    fi

    local result="${parts[0]}"
    local current_width
    current_width=$(visible_width "$result")

    for ((i = 1; i < ${#parts[@]}; i++)); do
        local part="${parts[$i]}"
        if [[ -z "$part" ]]; then
            continue
        fi
        local part_width
        part_width=$(visible_width "$part")
        if (( current_width + part_width <= max_width )); then
            result+="$part"
            (( current_width += part_width ))
        fi
    done

    echo -e "$result"
}

# Calculate context window - show remaining free space
context_info=""
total_size=$(echo "$input" | jq -r '.context_window.context_window_size // 0')
current_usage=$(echo "$input" | jq '.context_window.current_usage')
total_input_tokens=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
total_output_tokens=$(echo "$input" | jq -r '.context_window.total_output_tokens // 0')
cost_usd=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
lines_added=$(echo "$input" | jq -r '.cost.total_lines_added // 0')
lines_removed=$(echo "$input" | jq -r '.cost.total_lines_removed // 0')
model_id=$(echo "$input" | jq -r '.model.id // ""')
workspace_project_dir=$(echo "$input" | jq -r '.workspace.project_dir // ""' | tr ',' '_')

if [[ "$total_size" -gt 0 && "$current_usage" != "null" ]]; then
    # Get tokens from current_usage (includes cache)
    input_tokens=$(echo "$current_usage" | jq -r '.input_tokens // 0')
    cache_creation=$(echo "$current_usage" | jq -r '.cache_creation_input_tokens // 0')
    cache_read=$(echo "$current_usage" | jq -r '.cache_read_input_tokens // 0')

    # Total used from current request
    used_tokens=$((input_tokens + cache_creation + cache_read))

    # Calculate autocompact buffer (22.5% of context window = 45k for 200k)
    autocompact_buffer=$((total_size * 225 / 1000))

    # Free tokens calculation depends on autocompact setting
    if [[ "$autocompact_enabled" == "true" ]]; then
        # When AC enabled: subtract buffer to show actual usable space
        free_tokens=$((total_size - used_tokens - autocompact_buffer))
    else
        # When AC disabled: show full free space
        free_tokens=$((total_size - used_tokens))
    fi

    if [[ "$free_tokens" -lt 0 ]]; then
        free_tokens=0
    fi

    # Calculate percentage with one decimal (relative to total size)
    free_pct=$(awk "BEGIN {printf \"%.1f\", ($free_tokens * 100.0 / $total_size)}")

    # Format tokens based on token_detail setting
    if [[ "$token_detail_enabled" == "true" ]]; then
        # Use awk for portable comma formatting (works regardless of locale)
        free_display=$(awk -v n="$free_tokens" 'BEGIN { printf "%\047d", n }')
    else
        free_display=$(awk "BEGIN {printf \"%.1fk\", $free_tokens / 1000}")
    fi

    # Color based on MI thresholds (consistent with MI display)
    ctx_mi_val=$(compute_mi "$used_tokens" "$total_size" "$model_id" "$mi_curve_beta")
    ctx_util=$(awk -v u="$used_tokens" -v t="$total_size" 'BEGIN { if (t > 0) printf "%.4f", u/t; else print "0" }')
    ctx_color_name=$(get_mi_color "$ctx_mi_val" "$ctx_util")
    case "$ctx_color_name" in
        green)  ctx_color="$GREEN" ;;
        yellow) ctx_color="$YELLOW" ;;
        red)    ctx_color="$RED" ;;
    esac

    context_info=" | ${ctx_color}${free_display} (${free_pct}%)${RESET}"

    # Always show zone indicator
    zone_result=$(get_context_zone "$used_tokens" "$total_size")
    zone_word=$(echo "$zone_result" | awk '{print $1}')
    zone_color_name=$(echo "$zone_result" | awk '{print $2}')
    zone_ansi=$(zone_ansi_color "$zone_color_name")
    zone_info=" | ${zone_ansi}${zone_word}${RESET}"

    # Read previous entry if needed for delta OR MI
    if [[ "$show_delta_enabled" == "true" || "$show_mi_enabled" == "true" ]]; then
        # Use session_id for per-session state (avoids conflicts with parallel sessions)
        state_dir=~/.claude/statusline
        mkdir -p "$state_dir"

        # Migrate old state files from ~/.claude/ to ~/.claude/statusline/ (one-time migration)
        old_state_dir=~/.claude
        for old_file in "$old_state_dir"/statusline*.state; do
            if [[ -f "$old_file" ]]; then
                new_file="${state_dir}/$(basename "$old_file")"
                if [[ ! -f "$new_file" ]]; then
                    mv "$old_file" "$new_file" 2>/dev/null || true
                else
                    rm -f "$old_file" 2>/dev/null || true
                fi
            fi
        done

        if [[ -n "$session_id" ]]; then
            state_file=${state_dir}/statusline.${session_id}.state
        else
            state_file=${state_dir}/statusline.state
        fi
        has_prev=false
        prev_tokens=0
        if [[ -f "$state_file" ]]; then
            has_prev=true
            # Read last line and calculate previous state
            # CSV: ts[0],in[1],out[2],cur_in[3],cur_out[4],cache_create[5],cache_read[6],
            #      cost[7],+lines[8],-lines[9],session[10],model[11],dir[12],size[13]
            last_line=$(tail -1 "$state_file" 2>/dev/null)
            if [[ -n "$last_line" ]]; then
                prev_cur_in=$(echo "$last_line" | cut -d',' -f4)
                prev_cache_create=$(echo "$last_line" | cut -d',' -f6)
                prev_cache_read=$(echo "$last_line" | cut -d',' -f7)
                prev_tokens=$(( ${prev_cur_in:-0} + ${prev_cache_create:-0} + ${prev_cache_read:-0} ))
            fi
        fi

        # Calculate and display token delta if enabled
        if [[ "$show_delta_enabled" == "true" ]]; then
            delta=$((used_tokens - prev_tokens))
            if [[ "$has_prev" == "true" && "$delta" -gt 0 ]]; then
                if [[ "$token_detail_enabled" == "true" ]]; then
                    delta_display=$(awk -v n="$delta" 'BEGIN { printf "%\047d", n }')
                else
                    delta_display=$(awk "BEGIN {printf \"%.1fk\", $delta / 1000}")
                fi
                delta_info=" | ${DIM}+${delta_display}${RESET}"
            fi
        fi

        # Calculate and display MI score if enabled
        if [[ "$show_mi_enabled" == "true" ]]; then
            mi_val=$(compute_mi "$used_tokens" "$total_size" "$model_id" "$mi_curve_beta")
            mi_util=$(awk -v u="$used_tokens" -v t="$total_size" 'BEGIN { if (t > 0) printf "%.4f", u/t; else print "0" }')
            mi_color_name=$(get_mi_color "$mi_val" "$mi_util")
            case "$mi_color_name" in
                green)  mi_color="$GREEN" ;;
                yellow) mi_color="$YELLOW" ;;
                red)    mi_color="$RED" ;;
            esac
            mi_info=" | ${mi_color}MI:${mi_val}${RESET}"
        fi

        # Only append if context usage changed (avoid duplicates from multiple refreshes)
        cur_input_tokens=$(echo "$current_usage" | jq -r '.input_tokens // 0')
        cur_output_tokens=$(echo "$current_usage" | jq -r '.output_tokens // 0')
        if [[ "$has_prev" != "true" || "$used_tokens" != "$prev_tokens" ]]; then
            echo "$(date +%s),$total_input_tokens,$total_output_tokens,$cur_input_tokens,$cur_output_tokens,$cache_creation,$cache_read,$cost_usd,$lines_added,$lines_removed,$session_id,$model_id,$workspace_project_dir,$total_size" >>"$state_file"
            maybe_rotate_state_file "$state_file"
        fi
    fi
fi

# Display session_id if enabled
if [[ "$show_session_enabled" == "true" && -n "$session_id" ]]; then
    session_info=" | ${DIM}${session_id}${RESET}"
fi

# Output: [Model] directory | branch [changes] | XXk free (XX%) [+delta] [AC] [S:session_id]
base="${DIM}${model}${RESET} | ${BLUE}${dir_name}${RESET}"
max_width=$(get_terminal_width)
fit_to_width "$max_width" "$base" "$git_info" "$context_info" "$zone_info" "$mi_info" "$delta_info" "$session_info"
