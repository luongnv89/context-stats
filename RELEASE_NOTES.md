## v1.5.1 — 2026-03-11

### Bug Fixes
- **Fix session ID disappearing from statusline** — Claude Code runs statusline scripts as piped subprocesses with no real TTY, causing terminal width detection to always return 80 columns. This made `fit_to_width()` drop lower-priority parts like session ID even when the real terminal had plenty of space. Now uses 200 columns as default when no TTY is detected; Claude Code's own UI handles overflow.
- **Fix CI failures** — Resolve ESLint, Python 3.9 compatibility, and release workflow issues

### Other Changes
- Update logo SVG assets

**Full Changelog**: https://github.com/luongnv89/cc-context-stats/compare/v1.5.0...v1.5.1
