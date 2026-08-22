## Context

The project has 5 CSV writer implementations (Python `state.py`, Node.js `statusline.js`, bash `statusline-full.sh`/`statusline-mid.sh`/`statusline-min.sh`) and 1 reader (Python `StateEntry.from_csv_line`). All use naive comma-join for serialization and `split(",")` for parsing. The `workspace_project_dir` field (index 12) is the only string field that could contain commas — all others are numeric or controlled identifiers.

There is no format documentation. `docs/ARCHITECTURE.md` line 90 incorrectly states "Each line is a JSON record."

## Goals / Non-Goals

**Goals:**

- Document the 14-field CSV format as the canonical contract between writers and readers
- Prevent commas in `workspace_project_dir` from corrupting CSV rows
- Fix the incorrect JSON statement in ARCHITECTURE.md
- Keep the comma guard consistent across all 5 writer implementations

**Non-Goals:**

- Migrating to a proper CSV library (e.g., Python `csv` module) — the format is simple enough that manual serialization is fine for 14 fixed fields
- Adding RFC 4180 quoting — over-engineering for a single field where commas are extremely rare
- Retroactively fixing existing state files — they're append-only and transient
- Changing the CSV field order or adding/removing fields

## Decisions

### D1: Replace commas with underscores in `workspace_project_dir`

**Choice:** Before writing the CSV line, replace all `,` characters in the workspace path with `_`.

**Alternatives considered:**

- **RFC 4180 quoting** (wrap field in double-quotes): Would require updating all 5 writers and the parser to handle quoted fields. Overkill for a single field where commas are extremely rare in real paths.
- **Backslash escaping** (`\,`): Requires custom unescape logic in the parser. More complex than replacement with negligible benefit.
- **Drop commas entirely** (strip instead of replace): Loses information — `/a,b/c` becomes `/ab/c` which is a different path. Underscore replacement (`/a_b/c`) is more transparent.

**Rationale:** Underscore replacement is the simplest approach that preserves path readability, requires minimal code changes, and is trivially consistent across Python, Node.js, and bash.

### D2: Apply guard at serialization time, not at parse time

**Choice:** Sanitize `workspace_project_dir` in `to_csv_line()` and the equivalent writer code in all implementations. Do not modify the parser.

**Rationale:** The parser already handles the field positionally via `split(",")`. If the writer guarantees no commas in any field, the parser works correctly as-is. Changing the parser would add complexity for a case that won't occur once the guard is in place.

### D3: CSV_FORMAT.md as the single source of truth

**Choice:** Create `docs/CSV_FORMAT.md` with a field table (position, name, type, description) and example rows. Reference it from ARCHITECTURE.md rather than duplicating the format description.

**Rationale:** Having one canonical spec prevents drift between docs. The architecture doc already references state files — a cross-reference to CSV_FORMAT.md is cleaner than inlining the format.

## Risks / Trade-offs

- **[Underscore collision]** A path like `/a_b/c` is indistinguishable from a sanitized `/a,b/c`. → Acceptable because commas in directory names are vanishingly rare on all major OS platforms, and the path field is used only for display/grouping, not for filesystem access.
- **[Bash sed portability]** Using `sed` or `tr` for comma replacement in bash scripts. → Both are POSIX standard and available on all target platforms (macOS, Linux).
- **[Parity test impact]** The comma guard must produce identical output in Python and Node.js. → The parity test (`test_parity.bats`) feeds the same JSON to both implementations, so any inconsistency will be caught automatically. Test inputs should include a path with commas.
