#!/bin/bash
#
# cc-context-stats Installation Checker
# Verifies that both the statusline and context-stats CLI are properly installed
# regardless of installation method (shell installer or pip).
#
# Usage:
#   ./scripts/check-install.sh
#   curl -fsSL https://raw.githubusercontent.com/luongnv89/cc-context-stats/main/scripts/check-install.sh | bash
#

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
DIM='\033[2m'
RESET='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() {
    echo -e "  ${GREEN}✓${RESET} $1"
    PASS=$((PASS + 1))
}

fail() {
    echo -e "  ${RED}✗${RESET} $1"
    FAIL=$((FAIL + 1))
}

warn() {
    echo -e "  ${YELLOW}!${RESET} $1"
    WARN=$((WARN + 1))
}

info() {
    echo -e "  ${DIM}$1${RESET}"
}

# Detect which installation method was used
detect_install_method() {
    local methods=()

    if pip show cc-context-stats &>/dev/null 2>&1 || pip3 show cc-context-stats &>/dev/null 2>&1; then
        methods+=("pip")
    fi

    echo "${methods[@]}"
}

# Test that a command can process statusline JSON from stdin.
#
# F-BUG-011: the smoke JSON previously used an obsolete schema (token_usage.*,
# session.id) that no current build reads, so even a broken statusline passed
# vacuously — any input produces output via the render catch-all. The payload
# below exercises the CURRENT stdin schema, runs against a sandboxed HOME (so
# no user state is touched), and only passes when the rendered line actually
# contains the project directory name — which the crash fallback
# ("[Claude] ~") never includes. A deliberately broken statusline fails this.
test_statusline_command() {
    local cmd="$1"
    local smoke_home proj_dir test_json output exit_code
    smoke_home=$(mktemp -d)
    proj_dir="$smoke_home/smoke-project"
    mkdir -p "$proj_dir"
    test_json=$(printf '{
  "session_id": "check-install-smoke",
  "model": {"display_name": "Claude", "id": "claude-sonnet-4-20250514"},
  "workspace": {"current_dir": "%s", "project_dir": "%s"},
  "context_window": {
    "context_window_size": 200000,
    "total_input_tokens": 1000,
    "total_output_tokens": 500,
    "current_usage": {
      "input_tokens": 10000,
      "cache_creation_input_tokens": 500,
      "cache_read_input_tokens": 200,
      "output_tokens": 900
    }
  },
  "cost": {
    "total_cost_usd": 0.01,
    "total_api_duration_ms": 1200,
    "total_lines_added": 10,
    "total_lines_removed": 2
  }
}' "$proj_dir" "$proj_dir")

    output=$(
        cd / && {
            printf '%s\n' "$test_json" | HOME="$smoke_home" USERPROFILE="$smoke_home" \
                eval "$cmd" 2>/dev/null
        }
    )
    exit_code=$?
    rm -rf "$smoke_home"

    if [ $exit_code -ne 0 ] || [ -z "$output" ]; then
        return 1
    fi
    # A working statusline renders the project directory name; a broken one
    # emits the catch-all fallback or exits without meaningful output.
    case "$output" in
        *smoke-project*) return 0 ;;
        *) return 1 ;;
    esac
}

echo -e "${BLUE}cc-context-stats Installation Check${RESET}"
echo "====================================="
echo

# ─── Step 1: Detect installation method ───
echo -e "${BLUE}1. Installation Detection${RESET}"

METHODS=$(detect_install_method)
if [ -z "$METHODS" ]; then
    fail "No installation detected"
    info "Install via one of:"
    info "  curl -fsSL https://raw.githubusercontent.com/luongnv89/cc-context-stats/main/install.sh | bash"
    info "  pip install cc-context-stats"
    echo
    echo -e "${RED}Check failed: nothing is installed.${RESET}"
    exit 1
fi

for method in $METHODS; do
    pass "Detected installation method: $method"
done
echo

# ─── Step 2: Check statusline command availability ───
echo -e "${BLUE}2. Statusline Command${RESET}"

STATUSLINE_CMD=""
STATUSLINE_SOURCE=""

# Check claude-statusline in PATH (pip install)
if command -v claude-statusline &>/dev/null; then
    STATUSLINE_CMD="claude-statusline"
    STATUSLINE_SOURCE="PATH ($(command -v claude-statusline))"
fi

if [ -n "$STATUSLINE_CMD" ]; then
    pass "Statusline command found: $STATUSLINE_SOURCE"
else
    fail "No statusline command found"
    info "Install with: pip install cc-context-stats"
    info "Then ensure 'claude-statusline' is in PATH"
fi

# Test that the statusline command actually works
if [ -n "$STATUSLINE_CMD" ]; then
    if test_statusline_command "$STATUSLINE_CMD"; then
        pass "Statusline command produces output from JSON input"
    else
        fail "Statusline command failed to process test input"
        info "Try running: echo '{\"model\":{\"display_name\":\"Test\"}}' | $STATUSLINE_CMD"
    fi
fi
echo

# ─── Step 3: Check context-stats CLI availability ───
echo -e "${BLUE}3. Context-Stats CLI${RESET}"

CONTEXT_STATS_CMD=""
CONTEXT_STATS_SOURCE=""

if command -v context-stats &>/dev/null; then
    CONTEXT_STATS_CMD="context-stats"
    CONTEXT_STATS_SOURCE="PATH ($(command -v context-stats))"
    pass "context-stats in PATH: $CONTEXT_STATS_SOURCE"
else
    fail "context-stats CLI not found"
    info "Install with: pip install cc-context-stats"
fi

# Test context-stats --help
if [ -n "$CONTEXT_STATS_CMD" ]; then
    if $CONTEXT_STATS_CMD --help &>/dev/null 2>&1 || $CONTEXT_STATS_CMD -h &>/dev/null 2>&1; then
        pass "context-stats --help works"
    else
        warn "context-stats --help did not succeed (may still work)"
    fi
fi
echo

# ─── Step 4: Check Claude Code settings.json ───
echo -e "${BLUE}4. Claude Code Settings${RESET}"

SETTINGS_FILE="$HOME/.claude/settings.json"

if [ -f "$SETTINGS_FILE" ]; then
    pass "Settings file exists: $SETTINGS_FILE"

    # Check for statusLine configuration
    if command -v jq &>/dev/null; then
        SL_TYPE=$(jq -r '.statusLine.type // empty' "$SETTINGS_FILE" 2>/dev/null)
        SL_CMD=$(jq -r '.statusLine.command // empty' "$SETTINGS_FILE" 2>/dev/null)

        if [ "$SL_TYPE" = "command" ] && [ -n "$SL_CMD" ]; then
            pass "statusLine configured: type=command, command=$SL_CMD"

            # Verify the configured command actually exists/works
            # Expand ~ to $HOME for checking
            EXPANDED_CMD="${SL_CMD/#\~/$HOME}"

            if [ -x "$EXPANDED_CMD" ]; then
                pass "Configured statusline command is executable"
            elif command -v "$SL_CMD" &>/dev/null; then
                pass "Configured statusline command is in PATH"
            else
                fail "Configured statusline command not found: $SL_CMD"
                info "The command in settings.json does not exist or is not executable"
                if [ -n "$STATUSLINE_CMD" ]; then
                    info "Fix: update settings.json statusLine.command to: $STATUSLINE_CMD"
                fi
            fi
        else
            fail "statusLine not configured in settings.json"
            info "Add to $SETTINGS_FILE:"
            info '  "statusLine": { "type": "command", "command": "claude-statusline" }'
        fi
    else
        # No jq, try grep
        if grep -q '"statusLine"' "$SETTINGS_FILE" 2>/dev/null; then
            pass "statusLine entry found in settings.json (install jq for detailed check)"
        else
            fail "statusLine not configured in settings.json"
            info "Add to $SETTINGS_FILE:"
            info '  "statusLine": { "type": "command", "command": "claude-statusline" }'
        fi
    fi
else
    fail "Settings file not found: $SETTINGS_FILE"
    info "Create it with:"
    info '  echo '"'"'{"statusLine":{"type":"command","command":"claude-statusline"}}'"'"' > ~/.claude/settings.json'
fi
echo

# ─── Step 5: Check config file ───
echo -e "${BLUE}5. Configuration${RESET}"

CONFIG_FILE="$HOME/.claude/statusline.conf"
if [ -f "$CONFIG_FILE" ]; then
    pass "Config file exists: $CONFIG_FILE"
else
    warn "No config file at $CONFIG_FILE (defaults will be used)"
    info "Create one for customization - see README for options"
fi

# Check state directory
STATE_DIR="$HOME/.claude/statusline"
if [ -d "$STATE_DIR" ]; then
    STATE_COUNT=$(ls "$STATE_DIR"/statusline.*.state 2>/dev/null | wc -l | tr -d ' ')
    pass "State directory exists with $STATE_COUNT session file(s)"
else
    warn "State directory not yet created: $STATE_DIR"
    info "This is normal for fresh installs - it will be created on first Claude Code session"
fi
echo

# ─── Summary ───
echo -e "${BLUE}Summary${RESET}"
echo "======="

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}All checks passed!${RESET} ($PASS passed, $WARN warnings)"
    echo
    echo "Both statusline and context-stats are properly installed."
    echo "Restart Claude Code to activate the status line."
else
    echo -e "${RED}$FAIL check(s) failed${RESET}, $PASS passed, $WARN warnings"
    echo

    # Provide targeted fix guidance
    if [ -z "$STATUSLINE_CMD" ] && [ -z "$CONTEXT_STATS_CMD" ]; then
        echo "cc-context-stats is not installed. Install it with:"
        echo -e "  ${BLUE}pip install cc-context-stats${RESET}"
    elif [ -z "$STATUSLINE_CMD" ]; then
        echo "claude-statusline not found in PATH. Verify:"
        echo "  pip show cc-context-stats"
        echo "  Ensure pip's bin directory is in your PATH"
    elif [ -z "$CONTEXT_STATS_CMD" ]; then
        echo "context-stats not found in PATH. Verify:"
        echo "  pip show cc-context-stats"
        echo "  Ensure pip's bin directory is in your PATH"
    else
        echo "Components found but settings may need updating."
        echo "Check the failed items above for specific fix instructions."
    fi
fi

exit $FAIL
