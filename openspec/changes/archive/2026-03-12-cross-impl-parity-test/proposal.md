## Why

The Python (`scripts/statusline.py`) and Node.js (`scripts/statusline.js`) statusline implementations share no code, schema contract, or cross-validation. Known drift already exists: terminal width defaults differ (200 vs 80), delta calculation reads different CSV fields, and write-frequency behavior diverges. Without an automated parity test, these divergences will continue to accumulate silently, causing inconsistent user experiences depending on which runtime Claude Code invokes.

## What Changes

- Add a CI integration test that feeds identical JSON fixtures to both Python and Node.js statusline scripts
- Assert that both produce equivalent stdout output (after normalizing terminal width via `COLUMNS` env var)
- Assert that both write identical CSV state file lines (same field count, same field values for the same input)
- Add the parity test to the existing GitHub Actions CI matrix so it runs on every PR
- Use the 5 existing shared fixtures in `tests/fixtures/json/` (`valid_full.json`, `valid_minimal.json`, `low_usage.json`, `medium_usage.json`, `high_usage.json`)

## Capabilities

### New Capabilities

- `cross-impl-parity`: Integration test that validates Python and Node.js statusline scripts produce equivalent stdout and CSV state output for identical JSON input

### Modified Capabilities

(none)

## Impact

- **CI pipeline**: New test job added to `.github/workflows/ci.yml` requiring both Python and Node.js runtimes in the same runner
- **Test fixtures**: Leverages existing `tests/fixtures/json/` — no new fixtures needed
- **Scripts**: `scripts/statusline.py` and `scripts/statusline.js` are tested as black-box executables (no code changes to them)
- **Known gaps surfaced**: The test will immediately expose the terminal width default discrepancy and any CSV field ordering differences, forcing fixes before the test can pass green
