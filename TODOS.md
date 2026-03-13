# TODOs

Items identified from the HOLD SCOPE mega review (2026-03-12).

## P1 — High Priority

### ~~1. Cross-implementation parity test~~ ✅ Done
**What:** Add a CI integration test that feeds identical JSON to both Python (`statusline.py`) and Node.js (`statusline.js`) scripts and asserts they write identical CSV state lines and produce equivalent stdout.
**Why:** The two implementations share no code or schema contract. Drift has occurred before and will occur again. This catches it automatically.
**Effort:** S
**Depends on:** None
**Status:** Implemented in `tests/bash/test_parity.bats` with CI job in `.github/workflows/ci.yml`. Archived as `openspec/changes/archive/2026-03-12-cross-impl-parity-test/`.

### ~~2. Document CSV state file format + comma guard~~ ✅ Done
**What:** Create `docs/CSV_FORMAT.md` documenting all 14 fields with types and examples. Fix `docs/ARCHITECTURE.md` which incorrectly states "each line is a JSON record." Sanitize `workspace_project_dir` to strip/escape commas before CSV serialization (in both Python and Node.js).
**Why:** The CSV format is an implicit contract across 5 writer implementations with zero documentation. Commas in directory paths silently corrupt rows.
**Effort:** S
**Depends on:** None
**Status:** Created `docs/CSV_FORMAT.md`, fixed ARCHITECTURE.md JSON→CSV, added comma→underscore guard in Python (`state.py`, `statusline.py`), Node.js (`statusline.js`), and bash (`statusline-full.sh`). Parity test with comma fixture passes. Archived as `openspec/changes/archive/2026-03-12-csv-format-doc-comma-guard/`.

### ~~3. Stderr logging for critical error paths~~ ✅ Done
**What:** Replace `except OSError: pass` with `sys.stderr.write()` warnings in: `StateFile.append_entry()`, `Config._create_default()`, `Config._read_config()`. Add `UnicodeDecodeError` to config read exception handling. Apply equivalent changes in `statusline.js`.
**Why:** State write failures cause silent data loss — users see stale dashboards with no indication of why. Statusline output goes to stdout (consumed by Claude Code), so stderr is safe for diagnostics.
**Effort:** S
**Depends on:** None
**Status:** Added `[statusline] warning:` stderr messages to all critical data pipeline error handlers in `config.py`, `state.py`, `statusline.py`, and `statusline.js`. Added `UnicodeDecodeError` to config read exception handling in both Python files. Non-critical handlers (git info, file migration) left silent.

### ~~4. Core data pipeline unit tests~~ ✅ Done
**What:** Add test files covering: (1) `StateEntry.from_csv_line` ↔ `to_csv_line` round-trip, (2) `calculate_deltas` and `detect_spike`, (3) zone threshold logic in `render_summary`. Cover edge cases: empty data, single entry, negative deltas, boundary percentages (39%/40%/79%/80%).
**Why:** The primary user-facing feature (`context-stats` CLI) has zero unit tests on its core logic — CSV parsing, statistics, and zone detection are all untested.
**Effort:** M
**Depends on:** None
**Status:** Implemented in `tests/python/test_data_pipeline.py` with 51 tests across 6 classes: TestStateEntryRoundTrip (14), TestStateEntryProperties (3), TestCalculateDeltas (8), TestCalculateStats (6), TestDetectSpike (10), TestZoneThresholds (10). Covers CSV round-trip with old/new formats, comma sanitization, boundary spike detection (exact 15%/3x thresholds), and zone boundaries at 39/40% and 79/80%.

## P2 — Medium Priority

### 5. State file cap + rotate
**What:** After `StateFile.append_entry()`, check line count. If >10,000 lines, truncate to the most recent 5,000. Apply in both Python and Node.js writers.
**Why:** State files are append-only with no rotation. `read_history()` loads entire files into memory. Heavy users could accumulate 50k+ lines across long sessions.
**Effort:** S
**Depends on:** None

### 6. Sanitize session_id input
**What:** Reject session IDs containing `/`, `\`, or `..` at the CLI entry point (`parse_args`) and in `StateFile.__init__()`. Print a clear error message and exit.
**Why:** Defense-in-depth against path traversal via `context-stats ../../etc/passwd`. Claude Code generates safe UUIDs, but the CLI accepts arbitrary user input.
**Effort:** XS
**Depends on:** None

### 7. Node.js git command timeout
**What:** Add `timeout: 5000` to both `execSync` calls in `statusline.js` `getGitInfo()`.
**Why:** Python's `get_git_info()` has `timeout=5`. Node.js has none — git hangs (network FS, large repo) would block the statusline process indefinitely.
**Effort:** XS
**Depends on:** None

### 8. Repo-level CLAUDE.md
**What:** Create `CLAUDE.md` at repo root documenting: project purpose, dual-implementation rationale, CSV format contract, test running instructions (`pytest`, `npm test`, `bats`), key architectural decisions, and the 5-script statusline landscape.
**Why:** Helps AI assistants and new contributors understand the project quickly. Currently the only CLAUDE.md is the user's personal global one.
**Effort:** S
**Depends on:** TODO 2 (CSV format doc) for cross-reference

## P3 — Low Priority

### 9. Add --version flag to context-stats CLI
**What:** Add `--version` argument to `parse_args()` that prints `cc-context-stats {version}` and exits.
**Why:** Users can't determine installed version without running the full tool. The footer shows version but only on successful render.
**Effort:** XS
**Depends on:** None
