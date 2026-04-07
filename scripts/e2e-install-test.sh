#!/bin/bash
#
# E2E Clean Install Smoke Tests for cc-context-stats
#
# Validates the Python runtime installation from a fresh install and confirms
# all expected CLI commands are available and functional.
#
# Usage:
#   ./scripts/e2e-install-test.sh    # Run Python tests
#   ./scripts/e2e-install-test.sh --python  # Python only (same as above)
#
# Exit codes:
#   0  all tests passed
#   N  number of failed tests
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Color helpers ──────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    DIM='\033[2m'
    RESET='\033[0m'
else
    RED='' GREEN='' BLUE='' BOLD='' DIM='' RESET=''
fi

PASS=0
FAIL=0
FAILED_ITEMS=()

pass() { echo -e "  ${GREEN}✓${RESET} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${RESET} $1"; FAIL=$((FAIL + 1)); FAILED_ITEMS+=("$1"); }
info() { echo -e "  ${DIM}$1${RESET}"; }
section() { echo -e "\n${BLUE}${BOLD}$1${RESET}"; }

# Minimal JSON that every statusline implementation must accept
STATUSLINE_TEST_JSON='{"model":{"display_name":"Claude","model_id":"claude-sonnet-4-20250514"},"session":{"id":"e2e-test-session"},"token_usage":{"total_input":1000,"total_output":500,"cache_creation_input":0,"cache_read_input":0,"percentage_used":5},"workspace":{"project_dir":"/tmp/test"}}'

# ── Helpers ────────────────────────────────────────────────────────────────────

# Run a command and assert it exits 0 with non-empty output
assert_cmd_ok() {
    local label="$1"
    shift
    local output exit_code
    output=$("$@" 2>/dev/null) && exit_code=$? || exit_code=$?
    if [ "$exit_code" -eq 0 ] && [ -n "$output" ]; then
        pass "$label"
    else
        fail "$label (exit=$exit_code, output='${output:0:80}')"
    fi
}

# Run a command and assert it exits 0 (output may be empty)
assert_exits_ok() {
    local label="$1"
    shift
    local exit_code
    "$@" >/dev/null 2>&1 && exit_code=$? || exit_code=$?
    if [ "$exit_code" -eq 0 ]; then
        pass "$label"
    else
        fail "$label (exit=$exit_code)"
    fi
}

# Pipe JSON through a command and assert exit 0 with non-empty output.
# Usage: assert_statusline_ok "label" cmd [args...]
assert_statusline_ok() {
    local label="$1"
    shift
    local output exit_code
    output=$(echo "$STATUSLINE_TEST_JSON" | "$@" 2>/dev/null) && exit_code=$? || exit_code=$?
    if [ "$exit_code" -eq 0 ] && [ -n "$output" ]; then
        pass "$label"
    else
        fail "$label (exit=$exit_code, output='${output:0:80}')"
    fi
}

# ── Python E2E ─────────────────────────────────────────────────────────────────

run_python_e2e() {
    section "Python — Clean Install Smoke Test"

    local python_bin
    if command -v python3 &>/dev/null; then
        python_bin=python3
    elif command -v python &>/dev/null; then
        python_bin=python
    else
        fail "python3/python not found in PATH — skipping Python tests"
        return
    fi
    info "$python_bin $($python_bin --version 2>&1)"

    if ! command -v pip3 &>/dev/null && ! command -v pip &>/dev/null; then
        fail "pip3/pip not found in PATH — skipping Python tests"
        return
    fi
    # Create a temporary virtualenv for a clean install
    local venv_dir
    venv_dir=$(mktemp -d)
    # shellcheck disable=SC2064
    trap "rm -rf '$venv_dir'" EXIT

    if ! $python_bin -m venv "$venv_dir" &>/dev/null; then
        fail "Failed to create virtualenv — skipping Python tests"
        rm -rf "$venv_dir"
        return
    fi
    pass "virtualenv created"
    info "venv: $venv_dir"

    local venv_python="$venv_dir/bin/python"
    local venv_pip="$venv_dir/bin/pip"

    # Install the package from source into the venv
    if ! "$venv_pip" install --quiet "$PROJECT_ROOT" &>/dev/null; then
        fail "pip install failed"
        rm -rf "$venv_dir"
        return
    fi
    pass "pip install succeeded"

    local venv_bin="$venv_dir/bin"

    # Assert: claude-statusline command exists and is executable
    if [ -x "$venv_bin/claude-statusline" ]; then
        pass "claude-statusline installed"
    else
        fail "claude-statusline not found in venv/bin after pip install"
    fi

    # Assert: context-stats command exists and is executable
    if [ -x "$venv_bin/context-stats" ]; then
        pass "context-stats installed"
    else
        fail "context-stats not found in venv/bin after pip install"
    fi

    # Assert: claude-statusline accepts JSON and produces output
    assert_statusline_ok "claude-statusline processes JSON input" "$venv_bin/claude-statusline"

    # Assert: context-stats --help exits 0 with output
    assert_cmd_ok "context-stats --help exits 0 with output" "$venv_bin/context-stats" --help

    # Assert: standalone statusline.py processes JSON
    local statusline_py="$PROJECT_ROOT/scripts/statusline.py"
    if [ -f "$statusline_py" ]; then
        assert_statusline_ok "scripts/statusline.py processes JSON input" "$venv_python" "$statusline_py"
    else
        info "scripts/statusline.py not found — skipping standalone script test"
    fi

    rm -rf "$venv_dir"
}

# ── Main ───────────────────────────────────────────────────────────────────────

main() {
    echo -e "${BLUE}${BOLD}cc-context-stats E2E Install Tests${RESET}"
    echo "======================================"

    # Parse flags
    for arg in "$@"; do
        case "$arg" in
            --python) ;;  # default, accepted for compatibility
            --help|-h)
                echo "Usage: $0 [--python]"
                echo "  --python  Test Python runtime (default)"
                exit 0
                ;;
        esac
    done

    run_python_e2e

    # ── Summary ────────────────────────────────────────────────────────────────
    echo
    echo "────────────────────────────────────────"
    if [ $FAIL -eq 0 ]; then
        echo -e "${GREEN}${BOLD}All E2E tests passed${RESET} ($PASS passed)"
    else
        echo -e "${RED}${BOLD}$FAIL test(s) failed${RESET}, $PASS passed"
        echo
        echo "Failed:"
        for item in "${FAILED_ITEMS[@]}"; do
            echo -e "  ${RED}✗${RESET} $item"
        done
    fi

    exit $FAIL
}

main "$@"
