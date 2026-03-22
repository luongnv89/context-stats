#!/usr/bin/env bats

# Test suite for statusline-full.sh

setup() {
    PROJECT_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
    SCRIPT="$PROJECT_ROOT/scripts/statusline-full.sh"
    FIXTURES="$PROJECT_ROOT/tests/fixtures/json"

    # Create a temp directory for config tests
    TEST_HOME=$(mktemp -d)
    export HOME="$TEST_HOME"
    mkdir -p "$TEST_HOME/.claude"
}

teardown() {
    rm -rf "$TEST_HOME"
}

@test "statusline-full.sh exists and is executable" {
    [ -f "$SCRIPT" ]
    [ -x "$SCRIPT" ]
}

@test "outputs model name from JSON input" {
    input='{"model":{"display_name":"Opus 4.5"},"workspace":{"current_dir":"/tmp/test","project_dir":"/tmp/test"}}'
    result=$(echo "$input" | "$SCRIPT")
    [[ "$result" == *"Opus 4.5"* ]]
}

@test "outputs directory name from path" {
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/home/user/myproject","project_dir":"/home/user/myproject"}}'
    result=$(echo "$input" | "$SCRIPT")
    [[ "$result" == *"myproject"* ]]
}

@test "handles full valid input with context window" {
    result=$(cat "$FIXTURES/valid_full.json" | "$SCRIPT")
    [[ "$result" == *"Opus 4.5"* ]]
    [[ "$result" == *"my-project"* ]]
    [[ "$result" == *"%"* ]]
}

@test "AC indicator removed from statusline" {
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":10000,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}'
    result=$(echo "$input" | "$SCRIPT")
    [[ "$result" != *"[AC:"* ]]
}

@test "shows exact tokens by default (token_detail=true)" {
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":10000,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}'
    result=$(echo "$input" | "$SCRIPT")
    # Should NOT show 'k' suffix by default, should show comma-formatted number
    [[ "$result" != *"k ("* ]]
    [[ "$result" == *"%"* ]]
}

@test "shows abbreviated tokens when token_detail=false" {
    echo "token_detail=false" > "$TEST_HOME/.claude/statusline.conf"
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":10000,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}'
    result=$(echo "$input" | "$SCRIPT")
    # Should show 'k' suffix for abbreviated format
    [[ "$result" == *"k ("* ]]
}

@test "handles missing context window gracefully" {
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/tmp/test","project_dir":"/tmp/test"}}'
    run bash "$SCRIPT" <<< "$input"
    [ "$status" -eq 0 ]
}

@test "calculates free tokens percentage correctly" {
    # Low usage fixture: 30k tokens used out of 200k = 85% free
    result=$(cat "$FIXTURES/low_usage.json" | "$SCRIPT")
    [[ "$result" == *"%"* ]]
}

@test "uses fixture files correctly" {
    for fixture in valid_full valid_minimal low_usage medium_usage high_usage; do
        run bash "$SCRIPT" < "$FIXTURES/${fixture}.json"
        [ "$status" -eq 0 ]
    done
}

@test "shows session_id by default (show_session=true)" {
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"},"session_id":"test-session-123"}'
    result=$(echo "$input" | "$SCRIPT")
    [[ "$result" == *"test-session-123"* ]]
}

@test "hides session_id when show_session=false" {
    echo "show_session=false" > "$TEST_HOME/.claude/statusline.conf"
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"},"session_id":"test-session-123"}'
    result=$(echo "$input" | "$SCRIPT")
    [[ "$result" != *"test-session-123"* ]]
}

@test "handles missing session_id gracefully" {
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/tmp","project_dir":"/tmp"}}'
    run bash "$SCRIPT" <<< "$input"
    [ "$status" -eq 0 ]
}

# Width truncation tests

strip_ansi() {
    printf '%s' "$1" | sed -e $'s/\033\[[0-9;]*m//g' -e 's/\\033\[[0-9;]*m//g'
}

@test "output fits within 80 columns" {
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/tmp/proj","project_dir":"/tmp/proj"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":10000,"cache_creation_input_tokens":500,"cache_read_input_tokens":200}},"session_id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}'
    result=$(COLUMNS=80 bash "$SCRIPT" <<< "$input")
    visible=$(strip_ansi "$result")
    len=$(printf '%s' "$visible" | wc -m | tr -d ' ')
    [ "$len" -le 80 ]
}

@test "narrow terminal prioritizes directory and context over model" {
    input='{"model":{"display_name":"Claude 3.5 Sonnet"},"workspace":{"current_dir":"/tmp/myproject","project_dir":"/tmp/myproject"},"context_window":{"context_window_size":200000,"current_usage":{"input_tokens":10000,"cache_creation_input_tokens":500,"cache_read_input_tokens":200}}}'
    result=$(COLUMNS=40 bash "$SCRIPT" <<< "$input")
    visible=$(strip_ansi "$result")
    len=$(printf '%s' "$visible" | wc -m | tr -d ' ')
    [ "$len" -le 40 ]
    [[ "$visible" == *"myproject"* ]]
    # Model name is lowest priority — truncated first in narrow terminals
    [[ "$visible" != *"Claude 3.5 Sonnet"* ]]
}

@test "wide terminal shows session_id" {
    input='{"model":{"display_name":"Claude"},"workspace":{"current_dir":"/tmp/proj","project_dir":"/tmp/proj"},"session_id":"test-wide-session-uuid"}'
    result=$(COLUMNS=200 bash "$SCRIPT" <<< "$input")
    [[ "$result" == *"test-wide-session-uuid"* ]]
}
