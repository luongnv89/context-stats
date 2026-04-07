# CLAUDE.md

## Project Purpose

cc-context-stats provides real-time context window monitoring for Claude Code sessions. It tracks token consumption over time and displays live ASCII graphs so users can see how much context remains.

## Implementation

The statusline is implemented in Python. Claude Code invokes the statusline script via stdin JSON pipe — the script reads JSON from stdin and writes formatted text to stdout. The Python implementation persists state to CSV files read by the `context-stats` CLI.

## CSV Format Contract

State files are append-only CSV at `~/.claude/statusline/statusline.<session_id>.state` with 14 comma-separated fields. See [docs/CSV_FORMAT.md](docs/CSV_FORMAT.md) for the full field specification. Key constraint: `workspace_project_dir` has commas replaced with underscores before writing.

## Statusline Script

| Script | Language | State writes | Notes |
|---|---|---|---|
| `scripts/statusline.py` | Python 3 | Yes | Pip-installable via package |

## Test Commands

```bash
# Python tests
source venv/bin/activate
pytest tests/python/ -v

# Bash integration tests (install/check scripts)
bats tests/bash/test_check_install.bats tests/bash/test_context_stats_subcommands.bats tests/bash/test_e2e_install.bats tests/bash/test_install.bats

# All tests
pytest && bats tests/bash/test_check_install.bats tests/bash/test_context_stats_subcommands.bats tests/bash/test_e2e_install.bats tests/bash/test_install.bats
```

## Key Architectural Decisions

- **Append-only CSV state files** with rotation at 10,000 lines (keeps most recent 5,000)
- **No network requests** — all data stays local in `~/.claude/statusline/`
- **Session ID validation** — rejects `/`, `\`, `..`, and null bytes for path-traversal defense
- **5-second git command timeout** in the Python implementation
- **Config via `~/.claude/statusline.conf`** — simple key=value pairs

## Sync Points: Package vs Standalone Script

The following logic is duplicated between the installable package (`src/`) and the standalone script (`scripts/statusline.py`) and **must be kept in sync** when modified:

| Logic | Package (`src/`) | Standalone Python (`scripts/statusline.py`) |
|---|---|---|
| Config parsing | `core/config.py` | `read_config()` |
| Color name map | `core/colors.py:COLOR_NAMES` | `_COLOR_NAMES` |
| Color parser | `core/colors.py:parse_color()` | `_parse_color()` |
| Git info | `core/git.py:get_git_info()` | `get_git_info()` |
| State rotation | `core/state.py` | `maybe_rotate_state_file()` |
| MI profiles | `graphs/intelligence.py:MODEL_PROFILES` | `MODEL_PROFILES` |
| MI formula | `graphs/intelligence.py:calculate_context_pressure()` | `compute_mi()` |
| MI colors | `graphs/intelligence.py:get_mi_color()` | `get_mi_color()` |
| Zone indicator | `graphs/intelligence.py:get_context_zone()` | `get_context_zone()` |
| Zone constants | `ZONE_1M_*`, `ZONE_STD_*`, `LARGE_MODEL_THRESHOLD` | same |
| Per-property colors | `colors.py:ColorManager` props, `config.py:_COLOR_KEYS` | `_COLOR_KEYS`, per-property vars |

## Cross-References

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system architecture and data flow
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — setup, testing, and contribution guide
- [docs/CSV_FORMAT.md](docs/CSV_FORMAT.md) — state file field specification
