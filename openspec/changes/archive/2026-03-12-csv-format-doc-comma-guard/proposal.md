## Why

The CSV state file is the central data contract across 5 writer implementations (Python, Node.js, three bash scripts) and 1 reader (`context-stats` CLI), yet it has zero documentation. `docs/ARCHITECTURE.md` incorrectly describes it as JSON. Worse, the `workspace_project_dir` field is written without any comma escaping — a project path containing a comma silently corrupts every subsequent field in the row, breaking stats display with no error message.

## What Changes

- **New doc: `docs/CSV_FORMAT.md`** — formal specification of all 14 CSV fields with types, positions, and examples.
- **Fix `docs/ARCHITECTURE.md`** — correct the statement that calls state file lines "JSON records" to accurately describe CSV format.
- **Comma guard for `workspace_project_dir`** — sanitize (strip or replace) commas in the workspace path before CSV serialization in both Python (`state.py`) and Node.js (`statusline.js`). Apply the same guard in bash scripts.
- **Parsing resilience** — update `StateEntry.from_csv_line()` to handle sanitized paths correctly.

## Capabilities

### New Capabilities

- `csv-format-spec`: Formal documentation of the 14-field CSV state file format (field positions, types, constraints, examples).
- `comma-guard`: Sanitization of `workspace_project_dir` to prevent commas from corrupting CSV rows, applied across all writer implementations.

### Modified Capabilities

(none — no existing spec-level requirements are changing)

## Impact

- **Files modified**: `src/claude_statusline/core/state.py`, `scripts/statusline.js`, `scripts/statusline-full.sh`, `scripts/statusline-min.sh`, `scripts/statusline-mid.sh`, `docs/ARCHITECTURE.md`
- **Files created**: `docs/CSV_FORMAT.md`
- **Risk**: Low — comma replacement in paths is a safe transformation (commas in directory names are extremely rare). Existing state files with clean paths are unaffected.
- **Tests**: Parity test (`tests/bash/test_parity.bats`) validates Python/Node.js produce identical output, so the comma guard must be consistent across both.
