# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.9.1] - 2026-03-15

### Fixed

- **Version reporting** — `context-stats --version` now correctly reports the installed version. Previously, `__init__.py` and `context-stats.sh` were not bumped during release, causing stale version output

## [1.9.0] - 2026-03-15

### Added

- **Installation checker** (`scripts/check-install.sh`) — Verifies both statusline and context-stats CLI are properly installed regardless of method (bash, npm, pip). Checks command availability, settings.json configuration, and functional output. Runnable locally or via `curl | bash`
- **MI monotonicity tests** — 60 new tests across Python (25), Node.js (23), and Bash (12) ensuring MI score always reflects context length: more free context = higher MI. Tests cover CPS monotonicity, composite MI under varying ES/PS, fine-grained 1% resolution, zone alignment, and all beta values
- **Shared monotonicity test vectors** — `tests/fixtures/mi_monotonicity_vectors.json` with utilization steps, ES/PS scenarios, and beta variants for cross-implementation parity

### Fixed

- **npm bin entry** — Removed `claude-statusline` from npm bin (not a user-facing CLI)
- **Self-dependency** — Removed accidental self-dependency in package.json
- **Upgrade detection** — Installer now detects and reports version upgrades
- **npm package exports** — Added proper bin entries for `context-stats` CLI

## [1.8.0] - 2026-03-15

### Added

- **Model Intelligence (MI) score** — Heuristic quality score estimating answer quality based on context utilization, cache efficiency, and output productivity. Inspired by the Michelangelo paper (arXiv:2409.12640). Displayed as `MI:X.XX` in the statusline with green/yellow/red color coding
- **MI score in all implementations** — MI computation available across Python package, standalone Python, Node.js, and Bash (via `awk`) statusline scripts with full cross-implementation parity
- **MI timeseries graph** — `context-stats --type mi` renders MI score trajectory over time as an ASCII graph with decimal Y-axis labels
- **MI in session summary** — `context-stats` summary now shows MI score with sub-component breakdown (CPS, ES, PS) and interpretation text
- **Shared test vectors** — `tests/fixtures/mi_test_vectors.json` with 6 vectors ensuring Python and Node.js produce identical MI scores within ±0.01 tolerance
- **`label_fn` parameter for `render_timeseries()`** — Optional custom Y-axis label formatter, used by MI graph to display decimals instead of token counts
- **Bash feature parity** — `statusline-full.sh` now supports custom color overrides, state file rotation, MI score display, and all config keys (`show_mi`, `mi_curve_beta`, `reduced_motion`, `show_io_tokens`)
- **Config: `show_mi`** — Toggle MI score display (default: `true`)
- **Config: `mi_curve_beta`** — Adjust MI degradation curve shape (default: `1.5`)

### Changed

- **Compact context display** — Removed "free" word from context info (`872,748 (87.3%)` instead of `872,748 free (87.3%)`) across all implementations
- **Decoupled state reads from `show_delta`** — State file is now read when either `show_delta` or `show_mi` is enabled, allowing MI to work independently of delta display
- **Node.js terminal width default** — Changed from `80` to `200` when no TTY is detected (matching Python behavior), preventing `fitToWidth` from dropping statusline parts in Claude Code's subprocess

### Fixed

- **Node.js terminal width** — Fixed `getTerminalWidth()` defaulting to 80 in Claude Code's subprocess, which caused MI, delta, AC, and session parts to be silently dropped

## [1.7.0] - 2026-03-14

### Added

- **Configurable colors** - Custom color themes via `~/.claude/statusline.conf` using named colors (`bright_cyan`) or hex codes (`#7dcfff`). Six configurable slots: `color_green`, `color_yellow`, `color_red`, `color_blue`, `color_magenta`, `color_cyan`
- **`context-stats explain` command** - Diagnostic dump that pretty-prints Claude Code's JSON context with derived values (free tokens, autocompact buffer, effective free), active config, vim/agent/output_style extensions, and raw JSON. Supports `--no-color` flag
- **24-bit true color support** - Hex color codes (`#rrggbb`) are converted to ANSI 24-bit escape sequences for full RGB color customization
- **Cross-implementation sync documentation** - Added sync points table to CLAUDE.md documenting triplicated logic across Python, Node.js, and Bash implementations

### Changed

- **ColorManager accepts overrides** - `ColorManager` now takes an optional `overrides` dict, allowing config-driven color customization throughout the package
- **Git info uses configurable colors** - Branch and change count colors now respect user color overrides in all three implementations
- **Config parsing preserves raw values** - Config reader now preserves case for color values while lowercasing only for boolean comparison

## [1.6.2] - 2026-03-13

### Fixed

- **Delta calculation parity** - Python statusline now reads correct CSV indices (3+5+6) for context usage delta, matching Node.js behavior
- **Missing duplicate-entry guard** - Python statusline now skips state file writes when token count is unchanged, preventing file bloat
- **Missing state file rotation** - Python statusline now calls rotation after writes (10k/5k threshold), matching Node.js
- **Missing git timeout** - Added 5-second timeout to git subprocess calls in standalone Python statusline script
- **Broad exception handling** - Narrowed `except Exception` to `(OSError, ValueError)` for state reads and `OSError` for writes
- **Stale CSV format comments** - Added missing `context_window_size` field to header comments in both Python and Node.js scripts

### Added

- **Delta parity tests** - 4 new bats tests verifying Python/Node.js produce identical deltas, handle first-run/decrease/dedup correctly

## [1.6.1] - 2026-03-13

### Fixed

- **Footer version drift** - Corrected stale version `1.2.3` in bash script and `1.0.0` default in Python renderer to match actual release version
- **Footer project name** - Renamed `claude-statusline` to `cc-context-stats` in the footer display across bash and Python implementations
- **Install version embedding** - Install scripts now read version from `package.json` and embed it into the installed script, preventing future version drift

## [1.6.0] - 2026-03-13

### Added

- **CLI `--version` flag** - `context-stats --version` / `-V` now prints the current version
- **State file rotation** - Automatic rotation at 10,000 lines (keeps most recent 5,000) to prevent unbounded file growth
- **Session ID validation** - Rejects path-traversal characters (`/`, `\`, `..`, null bytes) for security
- **Git command timeout** - 5-second timeout on git operations in both Python and Node.js implementations
- **Core data pipeline unit tests** - 51 tests across 6 classes covering config, state, formatters, graph, and CLI
- **Cross-implementation parity test** - Ensures Python and Node.js statusline scripts produce consistent output
- **Stderr warnings** - Critical error paths now emit warnings to stderr for debugging
- **CSV format documentation** - Formal specification of the 14-field state file format
- **Comma guard for workspace paths** - Commas in `workspace_project_dir` are replaced with underscores before CSV write
- **Open-source standard files** - Added CODE_OF_CONDUCT.md, CONTRIBUTING.md, SECURITY.md, and GitHub issue/PR templates
- **NPM Package** - `cc-context-stats` now available on npm for JavaScript/Node.js environments

### Changed

- **Package Metadata** - Synchronized package descriptions across npm and PyPI for consistency
- **Installation Section** - Moved shell script installation to the top of README as the recommended method

### Dependencies

- Bumped prettier from 3.7.4 to 3.8.0

## [1.2.0] - 2025-01-08

### Added

- **Context Zones** - Status indicator based on context usage:
  - 🟢 Smart Zone (< 40%): "You are in the smart zone"
  - 🟡 Dumb Zone (40-80%): "You are in the dumb zone - Dex Horthy says so"
  - 🔴 Wrap Up Zone (> 80%): "Better to wrap up and start a new session"
- **Project name display** - Header now shows "Context Stats (project-name • session-id)"

### Changed

- **Watch mode enabled by default** - `context-stats` now runs in live monitoring mode (2s refresh)
- **Delta graph by default** - Shows "Context Growth Per Interaction" instead of both graphs
- Added `--no-watch` flag to show graphs once and exit
- Simplified installer - no script selection, auto-overwrite existing files
- Renamed graph labels to focus on context (e.g., "Context Usage Over Time")
- Cleaned up session summary - removed clutter, highlighted status

## [1.1.0] - 2025-01-08

### Changed

- **BREAKING**: Renamed package from `cc-statusline` to `cc-context-stats`
- **BREAKING**: Renamed `token-graph` CLI command to `context-stats`
- Pivoted project focus to real-time token monitoring and context tracking
- Updated tagline: "Never run out of context unexpectedly"

### Migration

If upgrading from `cc-statusline`:

```bash
pip uninstall cc-statusline
pip install cc-context-stats
```

The `claude-statusline` command still works. Replace `token-graph` with `context-stats`.

## [1.0.2] - 2025-01-08

### Fixed

- Fixed remaining context showing negative values in context-stats by using `current_used_tokens` instead of cumulative `total_input_tokens + total_output_tokens`
- Fixed ANSI escape codes not rendering properly in watch mode by using `sys.stdout.write()` instead of `print()` for cursor control sequences
- Fixed color codes in summary statistics using ColorManager instead of raw ANSI constants

## [1.0.1] - 2025-01-07

### Added

- pip/uv installable Python package (`cc-statusline` on PyPI)
- `context_window_size` field to state file for tracking remaining context
- Remaining context display in context-stats summary

### Fixed

- Restored executable permissions on script files
- Fixed stdin detection in pipe mode using INTERACTIVE flag

### Changed

- Cleaned up unused `show_io_tokens` option
- Fixed shellcheck warnings in shell scripts

## [1.0.0] - 2025-01-06

### Added

- Comprehensive test suite with Bats (Bash), pytest (Python), and Jest (Node.js)
- GitHub Actions CI/CD pipeline with multi-platform testing
- Code quality tools: ShellCheck, Ruff, ESLint, Prettier
- Pre-commit hooks for automated code quality checks
- EditorConfig for consistent formatting across editors
- CONTRIBUTING.md with development setup instructions
- Dependabot configuration for automated dependency updates
- Release automation workflow
- Full-featured status line script (`statusline-full.sh`)
- Git-aware status line script (`statusline-git.sh`)
- Minimal status line script (`statusline-minimal.sh`)
- Cross-platform Python implementation (`statusline.py`)
- Cross-platform Node.js implementation (`statusline.js`)
- Interactive installer script (`install.sh`)
- Configuration examples for Claude Code
- Autocompact (AC) buffer indicator
- Context window usage with color-coded percentages
- Git branch and uncommitted changes display

## [0.x] - Pre-release

Initial development versions with basic status line functionality.
