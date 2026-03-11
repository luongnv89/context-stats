## What's Changed

### Refactoring
- **Remove icon and pacman display options from statusline** — Simplify the statusline by removing `icon_mode` config option (`standard`/`pacman`/`off`), activity icons, and pacman meter visualization. Activity tier detection and text labels are preserved for context-stats. Net removal of ~413 lines across 10 files (#13) @luongnv89

### Bug Fixes
- **Eliminate watch mode flickering via double-buffered rendering** — Replace cursor-home + line-by-line overwrites with full-frame buffering that writes the entire screen in a single `sys.stdout.write()` call, eliminating visible flicker during watch mode refreshes

**Full Changelog**: https://github.com/luongnv89/cc-context-stats/compare/v1.4.0...v1.5.0
