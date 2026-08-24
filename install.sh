#!/bin/bash
#
# Claude Code Context Stats Installer
# Installs context-stats via pip and configures Claude Code settings
#
# Usage:
#   Local:  ./install.sh
#   Remote: curl -fsSL https://raw.githubusercontent.com/luongnv89/context-stats/main/install.sh | bash
#
# Requirements:
#   - Python 3 with pip
#   - jq (for automatic settings.json update, optional)
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

CLAUDE_DIR="$HOME/.claude"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"

echo -e "${BLUE}Claude Code Context Stats Installer${RESET}"
echo "====================================="
echo

# ─── Checks ──────────────────────────────────────────────────────────────────

check_python() {
    if command -v python3 &>/dev/null; then
        echo -e "${GREEN}✓${RESET} python3 found: $(python3 --version)"
    elif command -v python &>/dev/null; then
        echo -e "${GREEN}✓${RESET} python found: $(python --version)"
    else
        echo -e "${RED}Error: Python 3 is required but not found.${RESET}"
        echo "Install Python 3 from https://www.python.org/downloads/ and try again."
        exit 1
    fi
}

check_pip() {
    if command -v pip3 &>/dev/null; then
        PIP_CMD="pip3"
    elif command -v pip &>/dev/null; then
        PIP_CMD="pip"
    elif command -v python3 &>/dev/null; then
        PIP_CMD="python3 -m pip"
    elif command -v python &>/dev/null; then
        PIP_CMD="python -m pip"
    else
        echo -e "${RED}Error: pip not found.${RESET}"
        echo "Install pip and try again: https://pip.pypa.io/en/stable/installation/"
        exit 1
    fi
    echo -e "${GREEN}✓${RESET} pip found: $PIP_CMD"
}

check_jq() {
    if ! command -v jq &>/dev/null; then
        echo -e "${YELLOW}Warning: jq not installed — settings.json will need manual update.${RESET}"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "  Install with: brew install jq"
        else
            echo "  Install with: sudo apt install jq"
        fi
        JQ_AVAILABLE=false
    else
        echo -e "${GREEN}✓${RESET} jq found"
        JQ_AVAILABLE=true
    fi
}

# ─── Install ─────────────────────────────────────────────────────────────────

install_package() {
    echo
    echo "Installing context-stats..."
    if $PIP_CMD install --upgrade context-stats; then
        echo -e "${GREEN}✓${RESET} context-stats installed"
    else
        echo -e "${RED}Error: pip install failed.${RESET}"
        exit 1
    fi
}

# ─── Configure ───────────────────────────────────────────────────────────────

ensure_claude_dir() {
    if [ ! -d "$CLAUDE_DIR" ]; then
        mkdir -p "$CLAUDE_DIR"
        echo -e "${GREEN}✓${RESET} Created $CLAUDE_DIR"
    else
        echo -e "${GREEN}✓${RESET} Claude directory exists: $CLAUDE_DIR"
    fi
}

create_config() {
    CONFIG_FILE="$CLAUDE_DIR/statusline.conf"
    if [ -f "$CONFIG_FILE" ]; then
        echo -e "${GREEN}✓${RESET} Config file exists: $CONFIG_FILE"
        return
    fi

    cat >"$CONFIG_FILE" <<'EOF'
# context-stats — statusline configuration
# Full reference: https://github.com/luongnv89/context-stats/blob/main/docs/configuration.md

# ─── Display Settings ───────────────────────────────────────────────

# Autocompact setting — sync with Claude Code's /config
# When true, 22.5% of the context window is reserved for the autocompact buffer.
autocompact=true

# Token display format
# true  = exact count (e.g., 64,000)
# false = abbreviated  (e.g., 64.0k)
token_detail=true

# Show token delta since last refresh (e.g., +2,500)
show_delta=true

# Show session_id in the status line
show_session=true

# Disable rotating text animations (accessibility)
reduced_motion=false

# ─── Model Intelligence (MI) ────────────────────────────────────────

# Show the MI score in the status line
show_mi=false

# MI curve beta override (0 = use model-specific profile)
mi_curve_beta=0

# ─── Per-Property Colors ────────────────────────────────────────────
# Named colors: black, red, green, yellow, blue, magenta, cyan, white,
#   bright_black..bright_white, bold_white, dim
# Or hex: #rrggbb
#
# color_project_name=cyan
# color_branch_name=green
# color_mi_score=yellow
# color_zone=default
# color_separator=dim
EOF
    echo -e "${GREEN}✓${RESET} Created config file: $CONFIG_FILE"
}

update_settings() {
    echo

    if [ ! -f "$SETTINGS_FILE" ]; then
        echo '{}' >"$SETTINGS_FILE"
        echo -e "${GREEN}✓${RESET} Created $SETTINGS_FILE"
    fi

    if [ "$JQ_AVAILABLE" = true ]; then
        cp "$SETTINGS_FILE" "$SETTINGS_FILE.backup"
        jq '.statusLine = {"type": "command", "command": "claude-statusline"}' \
            "$SETTINGS_FILE.backup" >"$SETTINGS_FILE"
        rm "$SETTINGS_FILE.backup"
        echo -e "${GREEN}✓${RESET} Updated settings.json with statusLine configuration"
    else
        echo -e "${YELLOW}Note: Could not update settings.json (jq not installed)${RESET}"
        echo
        echo "Add this to $SETTINGS_FILE manually:"
        echo '  "statusLine": {'
        echo '    "type": "command",'
        echo '    "command": "claude-statusline"'
        echo '  }'
    fi
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
    check_python
    check_pip
    check_jq
    install_package
    ensure_claude_dir
    create_config
    update_settings

    echo
    echo -e "${GREEN}Installation complete!${RESET}"
    echo
    echo "Restart Claude Code to activate the status line."
    echo
    echo "To visualize token usage for any session:"
    echo "  context-stats <session_id>"
    echo
    echo "To generate a cross-project analytics report:"
    echo "  context-stats report"
    echo
    echo "To verify your installation:"
    echo "  context-stats doctor"
}

main
