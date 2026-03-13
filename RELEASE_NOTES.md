## v1.6.0 — 2026-03-13

### Features
- **CLI `--version` flag** — `context-stats --version` / `-V` now prints the current version
- **State file rotation** — Automatic rotation at 10,000 lines (keeps most recent 5,000) to prevent unbounded file growth
- **Session ID validation** — Rejects path-traversal characters (`/`, `\`, `..`, null bytes) for security
- **Git command timeout** — 5-second timeout on git operations in both Python and Node.js implementations
- **Core data pipeline unit tests** — 51 tests across 6 classes covering config, state, formatters, graph, and CLI
- **Cross-implementation parity test** — Ensures Python and Node.js statusline scripts produce consistent output
- **Stderr warnings** — Critical error paths now emit warnings to stderr for debugging
- **CSV format documentation** — Formal specification of the 14-field state file format
- **Comma guard for workspace paths** — Commas in `workspace_project_dir` are replaced with underscores before CSV write
- **Open-source standard files** — Added CODE_OF_CONDUCT.md, CONTRIBUTING.md, SECURITY.md, and GitHub issue/PR templates
- **NPM Package** — `cc-context-stats` now available on npm for JavaScript/Node.js environments

### Dependencies
- Bumped prettier from 3.7.4 to 3.8.0

**Full Changelog**: https://github.com/luongnv89/cc-context-stats/compare/v1.5.1...v1.6.0
