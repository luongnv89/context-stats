#!/bin/bash
# Minimal status line - shows model and current directory
# Usage: Copy to ~/.claude/statusline.sh and make executable

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
    # When running inside Claude Code's statusline subprocess, $COLUMNS is not set
    # and tput falls back to 80. If COLUMNS is set, trust it. Otherwise use 200
    # so no parts are dropped; Claude Code handles overflow.
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

base="[$MODEL_DISPLAY] $DIR_NAME"
max_width=$(get_terminal_width)
fit_to_width "$max_width" "$base"
