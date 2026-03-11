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

# Colors
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'

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
autocompact=""    # Will be set by sourced config
token_detail=""   # Will be set by sourced config
show_delta=""     # Will be set by sourced config
show_session=""   # Will be set by sourced config
ac_info=""
delta_info=""
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
EOF
fi

if [[ -f ~/.claude/statusline.conf ]]; then
    # shellcheck source=/dev/null
    source ~/.claude/statusline.conf
    if [[ "$autocompact" == "false" ]]; then
        autocompact_enabled=false
    fi
    if [[ "$token_detail" == "false" ]]; then
        token_detail_enabled=false
    fi
    if [[ "$show_delta" == "false" ]]; then
        show_delta_enabled=false
    fi
    if [[ "$show_session" == "false" ]]; then
        show_session_enabled=false
    fi
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
workspace_project_dir=$(echo "$input" | jq -r '.workspace.project_dir // ""')

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
        buffer_k=$(awk "BEGIN {printf \"%.0f\", $autocompact_buffer / 1000}")
        ac_info=" ${DIM}[AC:${buffer_k}k]${RESET}"
    else
        # When AC disabled: show full free space
        free_tokens=$((total_size - used_tokens))
        ac_info=" ${DIM}[AC:off]${RESET}"
    fi

    if [[ "$free_tokens" -lt 0 ]]; then
        free_tokens=0
    fi

    # Calculate percentage with one decimal (relative to total size)
    free_pct=$(awk "BEGIN {printf \"%.1f\", ($free_tokens * 100.0 / $total_size)}")
    free_pct_int=${free_pct%.*}

    # Format tokens based on token_detail setting
    if [[ "$token_detail_enabled" == "true" ]]; then
        # Use awk for portable comma formatting (works regardless of locale)
        free_display=$(awk -v n="$free_tokens" 'BEGIN { printf "%\047d", n }')
    else
        free_display=$(awk "BEGIN {printf \"%.1fk\", $free_tokens / 1000}")
    fi

    # Color based on free percentage
    if [[ "$free_pct_int" -gt 50 ]]; then
        ctx_color="$GREEN"
    elif [[ "$free_pct_int" -gt 25 ]]; then
        ctx_color="$YELLOW"
    else
        ctx_color="$RED"
    fi

    context_info=" | ${ctx_color}${free_display} free (${free_pct}%)${RESET}"

    # Calculate and display token delta if enabled
    if [[ "$show_delta_enabled" == "true" ]]; then
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
                    # New file exists, just remove old one
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
            # Read last line and calculate previous context usage
            # CSV: ts[0],in[1],out[2],cur_in[3],cur_out[4],cache_create[5],cache_read[6]
            last_line=$(tail -1 "$state_file" 2>/dev/null)
            if [[ -n "$last_line" ]]; then
                prev_cur_in=$(echo "$last_line" | cut -d',' -f4)
                prev_cache_create=$(echo "$last_line" | cut -d',' -f6)
                prev_cache_read=$(echo "$last_line" | cut -d',' -f7)
                prev_tokens=$(( ${prev_cur_in:-0} + ${prev_cache_create:-0} + ${prev_cache_read:-0} ))
            fi
        fi
        # Calculate delta
        delta=$((used_tokens - prev_tokens))
        # delta calculated for display
        # Only show positive delta (and skip first run when no previous state)
        if [[ "$has_prev" == "true" && "$delta" -gt 0 ]]; then
            if [[ "$token_detail_enabled" == "true" ]]; then
                delta_display=$(awk -v n="$delta" 'BEGIN { printf "%\047d", n }')
            else
                delta_display=$(awk "BEGIN {printf \"%.1fk\", $delta / 1000}")
            fi
            delta_info=" ${DIM}[+${delta_display}]${RESET}"
        fi
        # Only append if context usage changed (avoid duplicates from multiple refreshes)
        cur_input_tokens=$(echo "$current_usage" | jq -r '.input_tokens // 0')
        cur_output_tokens=$(echo "$current_usage" | jq -r '.output_tokens // 0')
        if [[ "$has_prev" != "true" || "$used_tokens" != "$prev_tokens" ]]; then
            # Append current usage with comprehensive format
            # Format: ts,in,out,cur_in,cur_out,cache_create,cache_read,cost,+lines,-lines,session,model,dir,size
            echo "$(date +%s),$total_input_tokens,$total_output_tokens,$cur_input_tokens,$cur_output_tokens,$cache_creation,$cache_read,$cost_usd,$lines_added,$lines_removed,$session_id,$model_id,$workspace_project_dir,$total_size" >>"$state_file"
        fi
    fi
fi

# Display session_id if enabled
if [[ "$show_session_enabled" == "true" && -n "$session_id" ]]; then
    session_info=" ${DIM}${session_id}${RESET}"
fi

# Output: [Model] directory | branch [changes] | XXk free (XX%) [+delta] [AC] [S:session_id]
base="${DIM}[${model}]${RESET} ${BLUE}${dir_name}${RESET}"
max_width=$(get_terminal_width)
fit_to_width "$max_width" "$base" "$git_info" "$context_info" "$delta_info" "$ac_info" "$session_info"
