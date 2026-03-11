#!/bin/bash
# Git-aware status line - shows model, directory, and git branch
# Usage: Copy to ~/.claude/statusline.sh and make executable

# Colors
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
RESET='\033[0m'

input=$(cat)

MODEL_DISPLAY=$(echo "$input" | jq -r '.model.display_name // "Claude"')
CURRENT_DIR=$(echo "$input" | jq -r '.workspace.current_dir // "~"')
DIR_NAME="${CURRENT_DIR##*/}"

# Width-fitting helpers
visible_width() {
    local stripped
    stripped=$(printf '%s' "$1" | sed -e $'s/\033\[[0-9;]*m//g' -e 's/\\033\[[0-9;]*m//g')
    printf '%s' "$stripped" | wc -m | tr -d ' '
}

get_terminal_width() {
    if [[ -n "$COLUMNS" ]]; then
        echo "$COLUMNS"
    else
        local cols
        cols=$(tput cols 2>/dev/null || echo 80)
        echo "$cols"
    fi
}

fit_to_width() {
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

# Git branch detection
GIT_INFO=""
if git -C "$CURRENT_DIR" rev-parse --git-dir > /dev/null 2>&1; then
    BRANCH=$(git -C "$CURRENT_DIR" branch --show-current 2>/dev/null)
    if [ -n "$BRANCH" ]; then
        # Count uncommitted changes
        CHANGES=$(git -C "$CURRENT_DIR" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
        if [ "$CHANGES" -gt 0 ]; then
            GIT_INFO=" | ${MAGENTA}${BRANCH}${RESET} ${CYAN}[${CHANGES}]${RESET}"
        else
            GIT_INFO=" | ${MAGENTA}${BRANCH}${RESET}"
        fi
    fi
fi

base="[${MODEL_DISPLAY}] ${BLUE}${DIR_NAME}${RESET}"
max_width=$(get_terminal_width)
fit_to_width "$max_width" "$base" "$GIT_INFO"
