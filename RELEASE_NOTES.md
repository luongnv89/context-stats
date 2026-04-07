## v1.17.0 — 2026-04-07

### Features
- **Cross-project token analytics** — `context-stats report` aggregates token usage and cost across all Claude Code projects and sessions, with breakdowns by project, model, and cache efficiency. Includes grand totals, per-project breakdown, top sessions, and cache read vs. creation ratios.

### Refactors
- **Python-only migration** — Removed the standalone `context-stats.sh` shell script; all functionality is now delivered through the Python package (`pip install cc-context-stats`)
- **Dropped Bash and Node.js implementations** — `scripts/statusline.js`, `scripts/statusline-full.sh`, `scripts/statusline-git.sh`, and `scripts/statusline-minimal.sh` have been removed; only `scripts/statusline.py` and the `src/` package remain

### Documentation
- Rewrote README to highlight key features, zones, Model Intelligence scoring, live graphs, session export, and cross-project analytics

**Full Changelog**: https://github.com/luongnv89/cc-context-stats/compare/v1.16.1...v1.17.0
