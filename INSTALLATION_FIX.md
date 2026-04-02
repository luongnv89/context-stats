# Installation Fix: Auto-Install Python Package

## Problem

When running `context-stats export <session_id>` from outside the project directory, users would get:

```
python3.14 -m claude_statusline.cli.context_stats: error: unrecognized arguments: <session_id>
```

### Root Cause

The `install.sh` script only installed the bash script to `~/.local/bin/context-stats`. It did NOT install the Python pip package `cc-context-stats`. 

When the bash script called `python3 -m claude_statusline.cli.context_stats`, it would use whatever Python package was installed globally. If it was an old version (e.g., v1.11.0), that version didn't have the `export` subcommand, so argparse rejected the session ID as an unrecognized argument.

## Solution

### 1. Auto-Install Python Package during Installation

Added `install_python_package()` function to `install.sh` that:

- Detects which pip command is available (`pip3`, `pip`, or `python3 -m pip`)
- Installs or upgrades `cc-context-stats` to match the current release version
- Handles the case where pip is not available with helpful instructions

This function is now called automatically during installation, right after the bash script is installed.

**Installation output example:**
```
✓ Installed: /Users/montimage/.claude/statusline.sh (v1.15.0)
✓ Installed: /Users/montimage/.local/bin/context-stats (v1.15.0)
✓ Python package installed: cc-context-stats==1.15.0
✓ Config file exists: /Users/montimage/.claude/statusline.conf
```

### 2. Version Validation in dispatch_python_subcommand()

Updated the `dispatch_python_subcommand()` function in `scripts/context-stats.sh` to:

- Check if the Python package is installed
- Verify that the installed package version matches the script version
- Show clear, actionable error messages if there's a mismatch

**Error messages:**

If package is missing entirely:
```
✗ Python package 'cc-context-stats' is not installed.
  Install it with: pip3 install cc-context-stats==1.15.0
```

If there's a version mismatch:
```
✗ Python package version mismatch:
    Script version:   1.15.0
    Package version:  1.11.0
  Run: pip3 install --upgrade cc-context-stats
```

### 3. Version Alignment

Updated VERSION in `scripts/context-stats.sh` from 1.11.1 to 1.15.0 to match `pyproject.toml`.

## How This Solves the Problem

**For new installations:**
- Users run `curl ... | bash` and get both the bash script AND the Python package automatically
- No additional steps required
- `context-stats export` works immediately

**For existing users:**
- If they upgrade and run the installer again, the Python package is automatically upgraded
- If they try to use `context-stats export` without the package, they see a clear error message with installation instructions
- Version mismatches are caught and the user is informed

## Testing

All tests pass:
- **Python tests:** 306 tests ✓
- **Node.js tests:** 84 tests ✓
- **Bash integration tests:** 66 tests ✓

Verified scenarios:
- ✓ Fresh installation from curl includes Python package
- ✓ `context-stats export <session_id>` works from any directory
- ✓ Missing package shows helpful error message
- ✓ Version mismatch warning is displayed
- ✓ All existing functionality still works

## Related Files Modified

- `install.sh` — Added `install_python_package()` function and called it from `main()`
- `scripts/context-stats.sh` — Updated `dispatch_python_subcommand()` with version checking, fixed VERSION to 1.15.0
