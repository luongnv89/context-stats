# CLAUDE.md

## Project Purpose

cc-context-stats provides real-time context window monitoring for Claude Code sessions. It tracks token consumption over time and displays live ASCII graphs so users can see how much context remains.

## Dual-Implementation Rationale

The statusline is implemented in three languages (Bash, Python, Node.js) so users can choose whichever runtime they have available. Claude Code invokes the statusline script via stdin JSON pipe — any implementation that reads JSON from stdin and writes formatted text to stdout works. The Python and Node.js implementations also persist state to CSV files read by the `context-stats` CLI.

## CSV Format Contract

State files are append-only CSV at `~/.claude/statusline/statusline.<session_id>.state` with 14 comma-separated fields. See [docs/CSV_FORMAT.md](docs/CSV_FORMAT.md) for the full field specification. Key constraint: `workspace_project_dir` has commas replaced with underscores before writing.

## Statusline Script Landscape

| Script | Language | State writes | Notes |
|---|---|---|---|
| `scripts/statusline-full.sh` | Bash | No | Full display, requires `jq` |
| `scripts/statusline-git.sh` | Bash | No | Git-focused variant |
| `scripts/statusline-minimal.sh` | Bash | No | Minimal variant |
| `scripts/statusline.py` | Python 3 | Yes | Pip-installable via package |
| `scripts/statusline.js` | Node.js | Yes | Standalone script |

## Test Commands

```bash
# Python tests
source venv/bin/activate
pytest tests/python/ -v

# Node.js tests
npm test

# Bash integration tests
bats tests/bash/*.bats

# All tests
pytest && npm test && bats tests/bash/*.bats
```

## Key Architectural Decisions

- **Append-only CSV state files** with rotation at 10,000 lines (keeps most recent 5,000)
- **No network requests** — all data stays local in `~/.claude/statusline/`
- **Session ID validation** — rejects `/`, `\`, `..`, and null bytes for path-traversal defense
- **5-second git command timeout** in both Python and Node.js implementations
- **Config via `~/.claude/statusline.conf`** — simple key=value pairs

## Cross-Implementation Sync Points

The following logic is duplicated across three implementations and **must be kept in sync** when modified:

| Logic | Package (`src/`) | Standalone Python (`scripts/statusline.py`) | Node.js (`scripts/statusline.js`) |
|---|---|---|---|
| Config parsing | `core/config.py` | `read_config()` | `readConfig()` |
| Color name map | `core/colors.py:COLOR_NAMES` | `_COLOR_NAMES` | `COLOR_NAMES` |
| Color parser | `core/colors.py:parse_color()` | `_parse_color()` | `parseColor()` |
| Git info | `core/git.py:get_git_info()` | `get_git_info()` | `getGitInfo()` |
| State rotation | `core/state.py` | `maybe_rotate_state_file()` | `maybeRotateStateFile()` |
| MI profiles | `graphs/intelligence.py:MODEL_PROFILES` | `MODEL_PROFILES` | `MODEL_PROFILES` |
| MI formula | `graphs/intelligence.py:calculate_context_pressure()` | `compute_mi()` | `computeMI()` |
| MI colors | `graphs/intelligence.py:get_mi_color()` | `get_mi_color()` | `getMIColor()` |
| Zone indicator | `graphs/intelligence.py:get_context_zone()` | `get_context_zone()` | `getContextZone()` |
| Zone constants | `ZONE_1M_*`, `ZONE_STD_*`, `LARGE_MODEL_THRESHOLD` | same | same |
| Per-property colors | `colors.py:ColorManager` props, `config.py:_COLOR_KEYS` | `_COLOR_KEYS`, per-property vars | `COLOR_CONFIG_KEYS`, per-property consts |

## Cross-References

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system architecture and data flow
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — setup, testing, and contribution guide
- [docs/CSV_FORMAT.md](docs/CSV_FORMAT.md) — state file field specification
