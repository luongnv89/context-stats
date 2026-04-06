#!/usr/bin/env bats

# Test suite for scripts/e2e-install-test.sh structure and contract.
# These tests validate that the E2E script itself is well-formed and contains
# all required runtime test sections, without running the slow full install.

setup() {
    PROJECT_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
    SCRIPT="$PROJECT_ROOT/scripts/e2e-install-test.sh"
}

@test "e2e-install-test.sh exists" {
    [ -f "$SCRIPT" ]
}

@test "e2e-install-test.sh is executable" {
    [ -x "$SCRIPT" ]
}

@test "e2e-install-test.sh has correct shebang" {
    head -1 "$SCRIPT" | grep -q "#!/bin/bash"
}

@test "e2e-install-test.sh passes bash syntax check" {
    bash -n "$SCRIPT"
}

@test "e2e-install-test.sh uses set -euo pipefail" {
    grep -q "set -euo pipefail" "$SCRIPT"
}

@test "e2e-install-test.sh contains Node.js test section" {
    grep -q "run_nodejs_e2e" "$SCRIPT"
    grep -q "npm install" "$SCRIPT"
    grep -q "statusline.js" "$SCRIPT"
}

@test "e2e-install-test.sh contains Python test section" {
    grep -q "run_python_e2e" "$SCRIPT"
    grep -q "virtualenv\|venv" "$SCRIPT"
    grep -q "claude-statusline" "$SCRIPT"
    grep -q "context-stats" "$SCRIPT"
}

@test "e2e-install-test.sh contains Bash test section" {
    grep -q "run_bash_e2e" "$SCRIPT"
    grep -q "statusline-full.sh" "$SCRIPT"
    grep -q "statusline-minimal.sh" "$SCRIPT"
    grep -q "statusline-git.sh" "$SCRIPT"
}

@test "e2e-install-test.sh reports pass/fail per test" {
    grep -q "pass()" "$SCRIPT"
    grep -q "fail()" "$SCRIPT"
    grep -q 'FAIL=$((FAIL + 1))' "$SCRIPT"
}

@test "e2e-install-test.sh exits with failure count" {
    grep -q 'exit $FAIL' "$SCRIPT"
}

@test "e2e-install-test.sh prints failed item names" {
    grep -q "FAILED_ITEMS" "$SCRIPT"
}

@test "e2e-install-test.sh accepts --nodejs flag" {
    grep -q '\-\-nodejs' "$SCRIPT"
}

@test "e2e-install-test.sh accepts --python flag" {
    grep -q '\-\-python' "$SCRIPT"
}

@test "e2e-install-test.sh accepts --bash flag" {
    grep -q '\-\-bash' "$SCRIPT"
}

@test "e2e-install-test.sh tests bash scripts in clean environment" {
    grep -q "env -i" "$SCRIPT"
}

@test "e2e-install-test.sh --help exits 0" {
    run bash "$SCRIPT" --help
    [ "$status" -eq 0 ]
}

@test "e2e-install-test.sh uses a test JSON payload for statusline assertions" {
    grep -q "STATUSLINE_TEST_JSON" "$SCRIPT"
    grep -q "token_usage" "$SCRIPT"
}
