## Context

The project has two independent statusline implementations — `scripts/statusline.py` (Python) and `scripts/statusline.js` (Node.js) — that both read JSON from stdin, write a CSV state line to `~/.claude/statusline/`, and emit a formatted status string to stdout. They share 5 JSON test fixtures in `tests/fixtures/json/` but have no test that compares their outputs against each other.

The existing CI pipeline (`ci.yml`) already has an `integration-test` job that runs both runtimes in the same runner, feeding them a hardcoded sample input. This is a smoke test only — it verifies each script exits cleanly, not that they produce equivalent output.

## Goals / Non-Goals

**Goals:**

- Detect stdout output drift between the two implementations for the same JSON input
- Detect CSV state file format drift (field count, field values, field ordering)
- Run automatically in CI on every PR, blocking merge on parity failures
- Normalize environmental variables (terminal width, state file directory, git) so comparisons are deterministic

**Non-Goals:**

- Fixing existing drift (terminal width defaults, delta calculation) — those are separate tasks
- Testing the Python package version (`src/claude_statusline/`) — only the `scripts/` versions
- Performance benchmarking or timing comparisons
- Testing bash wrapper scripts (`statusline-full.sh`, etc.)

## Decisions

### 1. Test format: Bats (bash) test file

**Choice:** Write the parity test as a new bats file at `tests/bash/test_parity.bats`.

**Rationale:** The test orchestrates two different runtimes (Python + Node.js) as black-box CLI processes. Bats is already used for bash integration tests in this project, the CI already installs bats, and shell is the natural language for piping JSON to two processes and comparing their outputs. A pytest or jest test would need subprocess calls anyway.

**Alternatives considered:**

- pytest with `subprocess.run()` — adds Python bias, requires Node.js to also be installed in the Python test matrix
- jest with `child_process.execSync()` — same issue in reverse
- Standalone shell script — loses bats assertion library and CI integration

### 2. Stdout comparison: strip ANSI, compare text content

**Choice:** Pipe both outputs through `sed` or `tr` to strip ANSI escape codes, then compare the cleaned strings. Set `COLUMNS=120` for both invocations to normalize terminal width.

**Rationale:** The raw stdout contains ANSI color codes that may vary in representation (e.g., `\033[0m` vs `\x1b[0m`). Stripping them makes comparisons stable. Setting `COLUMNS` explicitly avoids the known 200-vs-80 default discrepancy.

### 3. CSV comparison: field-by-field with tolerance

**Choice:** Compare CSV state lines field-by-field. Allow a 1-second tolerance on the timestamp field (index 0) since the two scripts run sequentially. All other 13 fields must match exactly.

**Rationale:** The scripts run serially, so timestamps will differ by the execution time of the first script. All other fields are deterministic given the same input. Field-by-field comparison gives clear error messages (e.g., "field 7 (cost_usd): Python=0.05234, Node=0.05") vs a binary diff.

### 4. State file isolation: use temp directory

**Choice:** Set a temporary directory as the state file location (via environment variable or by creating `~/.claude/statusline/` in a temp `$HOME`) so tests don't pollute the user's real state. Clean up after each test.

**Rationale:** Both scripts write to `~/.claude/statusline/statusline.{session_id}.state`. Using a temp `$HOME` isolates test state and prevents interference with parallel CI jobs or developer machines.

### 5. Git info: disable in parity tests

**Choice:** Run tests from a temporary directory outside any git repo (or set `GIT_DIR` to a non-existent path) so both scripts skip the git info segment.

**Rationale:** Git info (branch, dirty status) depends on the repo state at test time and is irrelevant to parity. Both implementations already gracefully handle missing `.git` by omitting the segment.

### 6. CI integration: new job in existing workflow

**Choice:** Add a `parity-test` job to `ci.yml` that depends on both `python-test` and `node-test`, runs on `ubuntu-latest` and `macos-latest`, and sets up both Python 3.11 and Node.js 20.

**Rationale:** Reuses the existing CI structure. Depending on both test jobs ensures we only run parity checks after the individual implementations pass their own tests. Two OS targets catch platform-specific formatting differences.

## Risks / Trade-offs

- **[Flaky timestamps]** → Mitigation: 1-second tolerance on field 0; if still flaky, increase to 2s or compare only non-timestamp fields.
- **[Existing drift blocks initial green]** → Mitigation: The test will initially fail on known discrepancies (width defaults, delta calc). These must be fixed in the scripts first, or the test must document and exclude known divergences with `# TODO` markers.
- **[Bats not available on Windows]** → Mitigation: Only run parity tests on ubuntu/macOS (matching existing bash-test matrix). Windows parity is out of scope — Claude Code statusline doesn't target Windows.
- **[New fixture added but parity test not updated]** → Mitigation: The test should glob `tests/fixtures/json/*.json` rather than hardcoding filenames, so new fixtures are automatically included.
