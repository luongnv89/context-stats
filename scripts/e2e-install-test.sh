#!/bin/bash
#
# E2E Clean Install Smoke Tests for cc-context-stats
#
# Validates each runtime implementation (Node.js, Python, Bash) from a fresh
# install and confirms all expected CLI commands are available and functional.
#
# Usage:
#   ./scripts/e2e-install-test.sh             # Run all three runtimes
#   ./scripts/e2e-install-test.sh --nodejs    # Node.js only
#   ./scripts/e2e-install-test.sh --python    # Python only
#   ./scripts/e2e-install-test.sh --bash      # Bash only
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
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    DIM='\033[2m'
    RESET='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' BOLD='' DIM='' RESET=''
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
    if [ $exit_code -eq 0 ] && [ -n "$output" ]; then
        pass "$label"
        return 0
    else
        fail "$label (exit=$exit_code, output='${output:0:80}')"
        return 1
    fi
}

# Run a command and assert it exits 0 (output may be empty)
assert_exits_ok() {
    local label="$1"
    shift
    local exit_code
    "$@" >/dev/null 2>&1 && exit_code=$? || exit_code=$?
    if [ $exit_code -eq 0 ]; then
        pass "$label"
        return 0
    else
        fail "$label (exit=$exit_code)"
        return 1
    fi
}

# Pipe JSON through a command and assert exit 0 with non-empty output
assert_statusline_ok() {
    local label="$1"
    local cmd="$2"
    local output exit_code
    output=$(echo "$STATUSLINE_TEST_JSON" | eval "$cmd" 2>/dev/null) && exit_code=$? || exit_code=$?
    if [ $exit_code -eq 0 ] && [ -n "$output" ]; then
        pass "$label"
        return 0
    else
        fail "$label (exit=$exit_code, output='${output:0:80}')"
        return 1
    fi
}

# ── Node.js E2E ────────────────────────────────────────────────────────────────

run_nodejs_e2e() {
    section "Node.js — Clean Install Smoke Test"

    # Prerequisites
    if ! command -v node &>/dev/null; then
        fail "node not found in PATH — skipping Node.js tests"
        return
    fi
    if ! command -v npm &>/dev/null; then
        fail "npm not found in PATH — skipping Node.js tests"
        return
    fi
    info "node $(node --version), npm $(npm --version)"

    local tmpdir
    tmpdir=$(mktemp -d)
    # shellcheck disable=SC2064
    trap "rm -rf '$tmpdir'" EXIT

    # Copy package files for a local install
    cp "$PROJECT_ROOT/package.json" "$tmpdir/"
    cp -r "$PROJECT_ROOT/scripts" "$tmpdir/scripts"

    info "Installing from $PROJECT_ROOT via npm pack..."
    local pack_file
    pack_file=$(cd "$PROJECT_ROOT" && npm pack --quiet 2>/dev/null)
    if [ -z "$pack_file" ]; then
        fail "npm pack failed — cannot perform clean Node.js install test"
        return
    fi

    local pack_path="$PROJECT_ROOT/$pack_file"

    # Install into a fresh directory
    local install_dir
    install_dir=$(mktemp -d)
    # shellcheck disable=SC2064
    trap "rm -rf '$install_dir' '$pack_path'" EXIT

    (cd "$install_dir" && npm install --quiet "$pack_path" 2>/dev/null)
    local npm_exit=$?
    rm -f "$pack_path"

    if [ $npm_exit -ne 0 ]; then
        fail "npm install failed (exit=$npm_exit)"
        rm -rf "$install_dir"
        return
    fi
    pass "npm install succeeded"

    local node_bin="$install_dir/node_modules/.bin"

    # Assert: context-stats entry point exists and is executable
    if [ -x "$node_bin/context-stats" ] || [ -L "$node_bin/context-stats" ]; then
        pass "context-stats entry point exists in node_modules/.bin"
    else
        fail "context-stats entry point missing from node_modules/.bin"
    fi

    # Assert: statusline.js script is present
    local statusline_js="$install_dir/node_modules/cc-context-stats/scripts/statusline.js"
    if [ -f "$statusline_js" ]; then
        pass "statusline.js present in installed package"
    else
        fail "statusline.js missing from installed package"
    fi

    # Assert: statusline.js accepts JSON and produces output
    assert_statusline_ok "statusline.js processes JSON input" "node '$statusline_js'"

    # Assert: context-stats --help exits 0
    local context_stats_sh="$install_dir/node_modules/cc-context-stats/scripts/context-stats.sh"
    if [ -f "$context_stats_sh" ]; then
        assert_exits_ok "context-stats.sh --help exits 0" bash "$context_stats_sh" --help
    else
        fail "context-stats.sh missing from installed package"
    fi

    rm -rf "$install_dir"
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
    local pip_bin
    pip_bin=$(command -v pip3 || command -v pip)

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
    assert_statusline_ok "claude-statusline processes JSON input" "'$venv_bin/claude-statusline'"

    # Assert: context-stats --help exits 0 with output
    assert_cmd_ok "context-stats --help exits 0 with output" "$venv_bin/context-stats" --help

    # Assert: standalone statusline.py processes JSON
    local statusline_py="$PROJECT_ROOT/scripts/statusline.py"
    if [ -f "$statusline_py" ]; then
        assert_statusline_ok "scripts/statusline.py processes JSON input" "'$venv_python' '$statusline_py'"
    else
        info "scripts/statusline.py not found — skipping standalone script test"
    fi

    rm -rf "$venv_dir"
}

# ── Bash E2E ───────────────────────────────────────────────────────────────────

run_bash_e2e() {
    section "Bash — Clean Environment Smoke Test"

    local bash_version
    bash_version=$(bash --version | head -1)
    info "$bash_version"

    # Expected Bash scripts (standalone, no external state needed)
    declare -a BASH_SCRIPTS=(
        "scripts/statusline-full.sh"
        "scripts/statusline-minimal.sh"
        "scripts/statusline-git.sh"
        "scripts/context-stats.sh"
        "scripts/check-install.sh"
    )

    # Assert: every script is executable
    for script in "${BASH_SCRIPTS[@]}"; do
        local script_path="$PROJECT_ROOT/$script"
        if [ -f "$script_path" ] && [ -x "$script_path" ]; then
            pass "$script is executable"
        elif [ -f "$script_path" ]; then
            fail "$script exists but is not executable"
        else
            fail "$script not found"
        fi
    done

    # Assert: statusline scripts accept JSON from stdin under clean environment
    # Use env -i to strip the environment (keep only PATH and HOME)
    local clean_env_prefix="env -i HOME=$HOME PATH=/usr/local/bin:/usr/bin:/bin"

    for script in "scripts/statusline-full.sh" "scripts/statusline-minimal.sh" "scripts/statusline-git.sh"; do
        local script_path="$PROJECT_ROOT/$script"
        if [ -f "$script_path" ] && [ -x "$script_path" ]; then
            # Check if jq is required and available
            if grep -q "jq" "$script_path" && ! command -v jq &>/dev/null; then
                info "$script requires jq (not available) — skipping JSON input test"
                continue
            fi
            local output exit_code
            output=$(echo "$STATUSLINE_TEST_JSON" | $clean_env_prefix bash "$script_path" 2>/dev/null) && exit_code=$? || exit_code=$?
            if [ $exit_code -eq 0 ] && [ -n "$output" ]; then
                pass "$script processes JSON in clean environment"
            else
                fail "$script failed in clean environment (exit=$exit_code)"
            fi
        fi
    done

    # Assert: context-stats.sh --help exits 0 in clean environment
    local cs_script="$PROJECT_ROOT/scripts/context-stats.sh"
    if [ -f "$cs_script" ] && [ -x "$cs_script" ]; then
        local exit_code
        $clean_env_prefix bash "$cs_script" --help >/dev/null 2>&1 && exit_code=$? || exit_code=$?
        if [ $exit_code -eq 0 ]; then
            pass "context-stats.sh --help exits 0 in clean environment"
        else
            fail "context-stats.sh --help failed in clean environment (exit=$exit_code)"
        fi
    fi

    # Assert: check-install.sh has correct shebang and is syntactically valid
    local ci_script="$PROJECT_ROOT/scripts/check-install.sh"
    if [ -f "$ci_script" ]; then
        assert_exits_ok "check-install.sh passes bash syntax check" bash -n "$ci_script"
    fi
}

# ── Main ───────────────────────────────────────────────────────────────────────

main() {
    echo -e "${BLUE}${BOLD}cc-context-stats E2E Install Tests${RESET}"
    echo "======================================"

    local run_nodejs=true
    local run_python=true
    local run_bash=true

    # Parse flags
    for arg in "$@"; do
        case "$arg" in
            --nodejs) run_nodejs=true;  run_python=false; run_bash=false ;;
            --python) run_nodejs=false; run_python=true;  run_bash=false ;;
            --bash)   run_nodejs=false; run_python=false; run_bash=true  ;;
            --help|-h)
                echo "Usage: $0 [--nodejs|--python|--bash]"
                echo "  --nodejs  Test Node.js runtime only"
                echo "  --python  Test Python runtime only"
                echo "  --bash    Test Bash scripts only"
                exit 0
                ;;
        esac
    done

    [ "$run_nodejs" = true ] && run_nodejs_e2e
    [ "$run_python" = true ] && run_python_e2e
    [ "$run_bash" = true ]   && run_bash_e2e

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
