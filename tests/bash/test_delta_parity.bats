#!/usr/bin/env bats

# Delta calculation parity tests: Python vs Node.js statusline scripts
# Verifies both implementations compute identical deltas from identical state.

strip_ansi() {
    printf '%s' "$1" | sed -e $'s/\033\[[0-9;]*m//g' -e 's/\\033\[[0-9;]*m//g'
}

setup() {
    PROJECT_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
    PYTHON_SCRIPT="$PROJECT_ROOT/scripts/statusline.py"
    NODE_SCRIPT="$PROJECT_ROOT/scripts/statusline.js"

    # Create isolated temp HOME so state files don't pollute real ~/.claude/
    TEST_HOME=$(mktemp -d)
    export HOME="$TEST_HOME"

    # Normalize terminal width for deterministic output
    export COLUMNS=200

    # Enable delta display
    mkdir -p "$TEST_HOME/.claude"
    echo "show_delta=true" > "$TEST_HOME/.claude/statusline.conf"

    # Create a non-git temp working directory so both scripts skip git info
    TEST_WORKDIR=$(mktemp -d)
    cd "$TEST_WORKDIR"
}

teardown() {
    rm -rf "$TEST_HOME"
    rm -rf "$TEST_WORKDIR"
}

# Helper: create a JSON payload with specific token values and session_id
make_payload() {
    local session="$1" input_tokens="$2" cache_creation="$3" cache_read="$4"
    cat <<EOF
{
  "model": {"display_name": "Opus 4.5"},
  "workspace": {"current_dir": "$TEST_WORKDIR", "project_dir": "$TEST_WORKDIR"},
  "session_id": "$session",
  "context_window": {
    "context_window_size": 200000,
    "current_usage": {
      "input_tokens": $input_tokens,
      "cache_creation_input_tokens": $cache_creation,
      "cache_read_input_tokens": $cache_read
    }
  }
}
EOF
}

# ============================================
# Delta Calculation Parity Tests
# ============================================

@test "delta parity: both scripts show identical delta after two sequential payloads" {
    # First payload: 30k context usage (10k input + 10k cache_create + 10k cache_read)
    local py_session="delta-parity-py"
    local node_session="delta-parity-node"

    local payload1_py=$(make_payload "$py_session" 10000 10000 10000)
    local payload1_node=$(make_payload "$node_session" 10000 10000 10000)

    # Run first payload (seeds state file, no delta shown)
    echo "$payload1_py" | python3 "$PYTHON_SCRIPT" > /dev/null 2>&1
    echo "$payload1_node" | node "$NODE_SCRIPT" > /dev/null 2>&1

    # Second payload: 80k context usage (40k input + 20k cache_create + 20k cache_read)
    # Expected delta = 80k - 30k = 50k
    local payload2_py=$(make_payload "$py_session" 40000 20000 20000)
    local payload2_node=$(make_payload "$node_session" 40000 20000 20000)

    local py_output=$(echo "$payload2_py" | python3 "$PYTHON_SCRIPT" 2>/dev/null)
    local node_output=$(echo "$payload2_node" | node "$NODE_SCRIPT" 2>/dev/null)

    local py_clean=$(strip_ansi "$py_output")
    local node_clean=$(strip_ansi "$node_output")

    # Both should contain [+50,000] delta
    if [[ "$py_clean" != *"[+50,000]"* ]]; then
        echo "Python output missing expected delta [+50,000]"
        echo "Python output: $py_clean"
        return 1
    fi
    if [[ "$node_clean" != *"[+50,000]"* ]]; then
        echo "Node.js output missing expected delta [+50,000]"
        echo "Node.js output: $node_clean"
        return 1
    fi

    # Compare outputs ignoring session_id suffix (which intentionally differs)
    # Strip the trailing session ID from both outputs for comparison
    local py_no_session=$(echo "$py_clean" | sed 's/ delta-parity-py$//')
    local node_no_session=$(echo "$node_clean" | sed 's/ delta-parity-node$//')

    if [ "$py_no_session" != "$node_no_session" ]; then
        echo "DELTA PARITY MISMATCH (ignoring session_id)"
        echo "Python:  $py_no_session"
        echo "Node.js: $node_no_session"
        return 1
    fi
}

@test "delta parity: no delta shown on first run (no previous state)" {
    local py_session="delta-first-py"
    local node_session="delta-first-node"

    local payload_py=$(make_payload "$py_session" 50000 10000 5000)
    local payload_node=$(make_payload "$node_session" 50000 10000 5000)

    local py_output=$(echo "$payload_py" | python3 "$PYTHON_SCRIPT" 2>/dev/null)
    local node_output=$(echo "$payload_node" | node "$NODE_SCRIPT" 2>/dev/null)

    local py_clean=$(strip_ansi "$py_output")
    local node_clean=$(strip_ansi "$node_output")

    # Neither should show a delta on first run
    if [[ "$py_clean" == *"[+"* ]]; then
        echo "Python should not show delta on first run"
        echo "Python output: $py_clean"
        return 1
    fi
    if [[ "$node_clean" == *"[+"* ]]; then
        echo "Node.js should not show delta on first run"
        echo "Node.js output: $node_clean"
        return 1
    fi
}

@test "delta parity: no delta shown when tokens decrease (context reset)" {
    local py_session="delta-decrease-py"
    local node_session="delta-decrease-node"

    # First payload: high usage
    local payload1_py=$(make_payload "$py_session" 80000 20000 10000)
    local payload1_node=$(make_payload "$node_session" 80000 20000 10000)

    echo "$payload1_py" | python3 "$PYTHON_SCRIPT" > /dev/null 2>&1
    echo "$payload1_node" | node "$NODE_SCRIPT" > /dev/null 2>&1

    # Second payload: lower usage (context was reset/compacted)
    local payload2_py=$(make_payload "$py_session" 20000 5000 5000)
    local payload2_node=$(make_payload "$node_session" 20000 5000 5000)

    local py_output=$(echo "$payload2_py" | python3 "$PYTHON_SCRIPT" 2>/dev/null)
    local node_output=$(echo "$payload2_node" | node "$NODE_SCRIPT" 2>/dev/null)

    local py_clean=$(strip_ansi "$py_output")
    local node_clean=$(strip_ansi "$node_output")

    # Neither should show delta when tokens decrease
    if [[ "$py_clean" == *"[+"* ]]; then
        echo "Python should not show delta when tokens decrease"
        echo "Python output: $py_clean"
        return 1
    fi
    if [[ "$node_clean" == *"[+"* ]]; then
        echo "Node.js should not show delta when tokens decrease"
        echo "Node.js output: $node_clean"
        return 1
    fi
}

@test "delta parity: duplicate guard prevents writing when tokens unchanged" {
    local py_session="delta-dedup-py"
    local node_session="delta-dedup-node"

    local payload_py=$(make_payload "$py_session" 50000 10000 5000)
    local payload_node=$(make_payload "$node_session" 50000 10000 5000)

    # Run same payload three times
    echo "$payload_py" | python3 "$PYTHON_SCRIPT" > /dev/null 2>&1
    echo "$payload_py" | python3 "$PYTHON_SCRIPT" > /dev/null 2>&1
    echo "$payload_py" | python3 "$PYTHON_SCRIPT" > /dev/null 2>&1

    echo "$payload_node" | node "$NODE_SCRIPT" > /dev/null 2>&1
    echo "$payload_node" | node "$NODE_SCRIPT" > /dev/null 2>&1
    echo "$payload_node" | node "$NODE_SCRIPT" > /dev/null 2>&1

    local py_state="$TEST_HOME/.claude/statusline/statusline.${py_session}.state"
    local node_state="$TEST_HOME/.claude/statusline/statusline.${node_session}.state"

    # Both should have written only 1 line (duplicate guard)
    local py_lines=$(wc -l < "$py_state" | tr -d ' ')
    local node_lines=$(wc -l < "$node_state" | tr -d ' ')

    if [ "$py_lines" -ne 1 ]; then
        echo "Python wrote $py_lines lines (expected 1 — duplicate guard failed)"
        return 1
    fi
    if [ "$node_lines" -ne 1 ]; then
        echo "Node.js wrote $node_lines lines (expected 1 — duplicate guard failed)"
        return 1
    fi
}
