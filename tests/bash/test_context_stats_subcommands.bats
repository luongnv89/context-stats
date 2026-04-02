#!/usr/bin/env bats

# Regression tests for the context-stats shell wrapper subcommand dispatch.

setup() {
    PROJECT_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
    SCRIPT="$PROJECT_ROOT/scripts/context-stats.sh"
}

@test "context-stats.sh delegates export subcommand to the Python CLI" {
    FAKE_BIN_DIR="$(mktemp -d)"
    CAPTURE_FILE="$(mktemp)"
    export CAPTURE_FILE

    cat >"$FAKE_BIN_DIR/python3" <<'EOF'
#!/usr/bin/env bash
# Handle version check by detecting import statement
if [[ "$*" == *"import claude_statusline"* ]]; then
    echo "1.15.0"
    exit 0
fi
# Capture all other arguments
printf '%s\n' "$@" > "$CAPTURE_FILE"
exit 0
EOF
    chmod +x "$FAKE_BIN_DIR/python3"

    run env PATH="$FAKE_BIN_DIR:$PATH" bash "$SCRIPT" export 6e551372-2428-4ed6-9346-ec3b605952ff --output report.md

    [ "$status" -eq 0 ]
    [ -f "$CAPTURE_FILE" ]

    [ "$(sed -n '1p' "$CAPTURE_FILE")" = "-m" ]
    [ "$(sed -n '2p' "$CAPTURE_FILE")" = "claude_statusline.cli.context_stats" ]
    [ "$(sed -n '3p' "$CAPTURE_FILE")" = "export" ]
    [ "$(sed -n '4p' "$CAPTURE_FILE")" = "6e551372-2428-4ed6-9346-ec3b605952ff" ]
    [ "$(sed -n '5p' "$CAPTURE_FILE")" = "--output" ]
    [ "$(sed -n '6p' "$CAPTURE_FILE")" = "report.md" ]
}
