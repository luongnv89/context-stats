#!/bin/bash
#
# Claude Code Context Stats Installer
# Installs and configures context monitoring for Claude Code
#
# Features:
#   - Real-time context usage monitoring (status line integration)
#   - Live dashboard with context-stats CLI tool
#   - Automatic detection of Smart Zone, Dumb Zone, and Wrap Up Zone
#   - Local data storage in ~/.claude/statusline/
#
# Usage:
#   Local:  ./install.sh
#   Remote: curl -fsSL https://raw.githubusercontent.com/luongnv89/cc-context-stats/main/install.sh | bash
#
# Requirements:
#   - curl (for remote installation)
#   - jq (for JSON configuration, optional but recommended)
#
# What gets installed:
#   - ~/.claude/statusline.sh - Status line command
#   - ~/.local/bin/context-stats - CLI tool for live context monitoring
#   - ~/.claude/statusline.conf - Configuration file
#   - ~/.claude/settings.json - Claude Code settings updated
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

CLAUDE_DIR="$HOME/.claude"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
LOCAL_BIN="$HOME/.local/bin"

# GitHub repository info for remote installation
GITHUB_RAW_URL="https://raw.githubusercontent.com/luongnv89/cc-context-stats/main"
GITHUB_API_URL="https://api.github.com/repos/luongnv89/cc-context-stats"

# Detect if running from pipe (curl) or locally
detect_install_mode() {
    # Check if we have a valid script file with scripts directory
    if [ -n "${BASH_SOURCE[0]}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        if [ -d "$SCRIPT_DIR/scripts" ]; then
            INSTALL_MODE="local"
            INTERACTIVE=true
            [ -t 0 ] || INTERACTIVE=false
            return
        fi
    fi
    # Running from curl/pipe or script directory not found
    INSTALL_MODE="remote"
    INTERACTIVE=false
}

echo -e "${BLUE}Claude Code Status Line Installer${RESET}"
echo "=================================="
echo

detect_install_mode

if [ "$INSTALL_MODE" = "remote" ]; then
    echo -e "${YELLOW}Remote installation mode${RESET}"
    echo "Downloading from GitHub..."
    echo
else
    echo -e "${GREEN}Local installation mode${RESET}"
    echo
fi

# Check for curl (required for remote installation)
check_curl() {
    if [ "$INSTALL_MODE" = "remote" ]; then
        if ! command -v curl &>/dev/null; then
            echo -e "${RED}Error: 'curl' is required for remote installation${RESET}"
            exit 1
        fi
    fi
}

# Check for jq (required for bash scripts)
check_jq() {
    if ! command -v jq &>/dev/null; then
        echo -e "${YELLOW}Warning: 'jq' is not installed.${RESET}"
        echo "jq is required for bash status line scripts."
        echo
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "Install with: brew install jq"
        else
            echo "Install with: sudo apt install jq (Debian/Ubuntu)"
            echo "         or: sudo yum install jq (RHEL/CentOS)"
        fi
        echo
        if [ "$INTERACTIVE" = true ]; then
            read -p "Continue anyway? (y/n) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        echo -e "${GREEN}✓${RESET} jq is installed"
    fi
}

# Download a file from GitHub
download_file() {
    local remote_path="$1"
    local dest_path="$2"
    local url="$GITHUB_RAW_URL/$remote_path"

    if curl -fsSL "$url" -o "$dest_path"; then
        chmod +x "$dest_path"
        return 0
    else
        echo -e "${RED}Error: Failed to download $remote_path${RESET}"
        return 1
    fi
}

# Get latest commit hash from GitHub
get_remote_commit_hash() {
    local hash
    hash=$(curl -fsSL "$GITHUB_API_URL/commits/main" 2>/dev/null | grep -m1 '"sha"' | cut -d'"' -f4 | head -c7)
    echo "${hash:-unknown}"
}

# Set script to install (full featured bash script)
select_script() {
    SCRIPT_REMOTE="scripts/statusline-full.sh"
    SCRIPT_NAME="statusline.sh"

    if [ "$INSTALL_MODE" = "local" ]; then
        SCRIPT_SRC="$SCRIPT_DIR/$SCRIPT_REMOTE"
    fi
}

# Create .claude directory if needed
ensure_claude_dir() {
    if [ ! -d "$CLAUDE_DIR" ]; then
        echo -e "${YELLOW}Creating $CLAUDE_DIR directory...${RESET}"
        mkdir -p "$CLAUDE_DIR"
    fi
    echo -e "${GREEN}✓${RESET} Claude directory exists: $CLAUDE_DIR"
}

# Install/copy script
install_script() {
    DEST="$CLAUDE_DIR/$SCRIPT_NAME"

    # Detect existing version for upgrade reporting
    local old_version=""
    if [ -f "$DEST" ]; then
        old_version=$(grep -o 'VERSION="[^"]*"' "$DEST" 2>/dev/null | head -1 | cut -d'"' -f2)
    fi

    if [ "$INSTALL_MODE" = "local" ]; then
        cp "$SCRIPT_SRC" "$DEST"
        chmod +x "$DEST"
    else
        download_file "$SCRIPT_REMOTE" "$DEST"
    fi

    # Get new version for reporting
    local new_version
    if [ "$INSTALL_MODE" = "local" ]; then
        new_version=$(grep -o '"version": *"[^"]*"' "$SCRIPT_DIR/package.json" | head -1 | grep -o '"[^"]*"$' | tr -d '"')
    else
        new_version=$(curl -fsSL "${GITHUB_RAW_URL}/package.json" 2>/dev/null | grep -o '"version": *"[^"]*"' | head -1 | grep -o '"[^"]*"$' | tr -d '"')
    fi

    if [ -n "$old_version" ] && [ "$old_version" != "$new_version" ]; then
        echo -e "${GREEN}✓${RESET} Upgraded: $DEST (${old_version} → ${new_version})"
    else
        echo -e "${GREEN}✓${RESET} Installed: $DEST (v${new_version:-unknown})"
    fi
}

# Install context-stats CLI tool
install_context_stats() {
    # Create ~/.local/bin if it doesn't exist
    if [ ! -d "$LOCAL_BIN" ]; then
        mkdir -p "$LOCAL_BIN"
    fi

    DEST="$LOCAL_BIN/context-stats"

    # Detect existing version for upgrade reporting
    local old_version=""
    if [ -f "$DEST" ]; then
        old_version=$(grep -o 'VERSION="[^"]*"' "$DEST" 2>/dev/null | head -1 | cut -d'"' -f2)
    fi

    # Get commit hash for version embedding
    local commit_hash
    if [ "$INSTALL_MODE" = "local" ]; then
        commit_hash=$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
        cp "$SCRIPT_DIR/scripts/context-stats.sh" "$DEST"
    else
        commit_hash=$(get_remote_commit_hash)
        download_file "scripts/context-stats.sh" "$DEST"
    fi

    # Embed version and commit hash
    local pkg_version
    if [ "$INSTALL_MODE" = "local" ]; then
        pkg_version=$(grep -o '"version": *"[^"]*"' "$SCRIPT_DIR/package.json" | head -1 | grep -o '"[^"]*"$' | tr -d '"')
    else
        pkg_version=$(curl -fsSL "${GITHUB_RAW_URL}/package.json" 2>/dev/null | grep -o '"version": *"[^"]*"' | head -1 | grep -o '"[^"]*"$' | tr -d '"')
    fi
    [ -n "$pkg_version" ] && sed -i.bak "s/VERSION=\"[^\"]*\"/VERSION=\"$pkg_version\"/" "$DEST" && rm -f "$DEST.bak"
    sed -i.bak "s/COMMIT_HASH=\"dev\"/COMMIT_HASH=\"$commit_hash\"/" "$DEST" && rm -f "$DEST.bak"
    chmod +x "$DEST"

    # Report install or upgrade
    if [ -n "$old_version" ] && [ "$old_version" != "$pkg_version" ]; then
        echo -e "${GREEN}✓${RESET} Upgraded: $DEST (${old_version} → ${pkg_version})"
    else
        echo -e "${GREEN}✓${RESET} Installed: $DEST (v${pkg_version:-unknown})"
    fi

    # Check if ~/.local/bin is in PATH
    if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
        echo
        echo -e "${YELLOW}Note: $LOCAL_BIN is not in your PATH${RESET}"
        echo "Add it to your shell configuration:"
        echo
        if [[ "$SHELL" == *"zsh"* ]]; then
            echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
            echo "  source ~/.zshrc"
        else
            echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
            echo "  source ~/.bashrc"
        fi
    fi
}

# Create config file with defaults if it doesn't exist
create_config() {
    CONFIG_FILE="$CLAUDE_DIR/statusline.conf"

    if [ -f "$CONFIG_FILE" ]; then
        echo -e "${GREEN}✓${RESET} Config file exists: $CONFIG_FILE"
        return
    fi

    cat >"$CONFIG_FILE" <<'EOF'
# Autocompact setting - sync with Claude Code's /config
autocompact=true

# Token display format
token_detail=true

# Show token delta since last refresh (adds file I/O on every refresh)
# Disable if you don't need it to reduce overhead
show_delta=true

# Show session_id in status line
show_session=true

# Disable rotating text animations
reduced_motion=false
EOF
    echo -e "${GREEN}✓${RESET} Created config file: $CONFIG_FILE"
}

# Update settings.json
update_settings() {
    echo

    # Create settings file if it doesn't exist
    if [ ! -f "$SETTINGS_FILE" ]; then
        echo '{}' >"$SETTINGS_FILE"
        echo -e "${GREEN}✓${RESET} Created $SETTINGS_FILE"
    fi

    # Check if jq is available for JSON manipulation
    if command -v jq &>/dev/null; then
        # Backup existing settings
        cp "$SETTINGS_FILE" "$SETTINGS_FILE.backup"

        # Add/update statusLine configuration
        SCRIPT_PATH="$HOME/.claude/$SCRIPT_NAME"
        jq --arg cmd "$SCRIPT_PATH" '.statusLine = {"type": "command", "command": $cmd}' \
            "$SETTINGS_FILE.backup" >"$SETTINGS_FILE"

        rm "$SETTINGS_FILE.backup"
        echo -e "${GREEN}✓${RESET} Updated settings.json with statusLine configuration"
    else
        echo -e "${YELLOW}Note: Could not update settings.json (jq not installed)${RESET}"
        echo
        echo "Please add this to $SETTINGS_FILE manually:"
        echo
        echo '  "statusLine": {'
        echo '    "type": "command",'
        echo "    \"command\": \"~/.claude/$SCRIPT_NAME\""
        echo '  }'
    fi
}

# Main installation
main() {
    check_curl
    check_jq
    ensure_claude_dir
    select_script
    install_script
    install_context_stats
    create_config
    update_settings

    echo
    echo -e "${GREEN}Installation complete!${RESET}"
    echo
    echo "Your status line is now configured."
    echo "Restart Claude Code to see the changes."
    echo
    echo "To customize, edit: $CLAUDE_DIR/$SCRIPT_NAME"
    echo "To change settings, edit: $CLAUDE_DIR/statusline.conf"
    echo
    echo "Run 'context-stats' to visualize token usage for any session."
}

main
