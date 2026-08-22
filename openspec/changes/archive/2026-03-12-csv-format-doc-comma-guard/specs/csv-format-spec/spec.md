## ADDED Requirements

### Requirement: CSV format documentation exists

The project SHALL have a `docs/CSV_FORMAT.md` file that documents the state file CSV format as the canonical reference for all writer and reader implementations.

#### Scenario: CSV_FORMAT.md contains complete field table

- **WHEN** a developer opens `docs/CSV_FORMAT.md`
- **THEN** the document SHALL contain a table listing all 14 fields with their position index (0–13), field name, data type, and description

#### Scenario: CSV_FORMAT.md includes example rows

- **WHEN** a developer reads `docs/CSV_FORMAT.md`
- **THEN** the document SHALL include at least one complete example CSV row with all 14 fields populated

### Requirement: CSV field order and types are specified

The CSV state file format SHALL consist of exactly 14 comma-separated fields per line, in the following fixed order:

| Index | Field | Type |
| ------- | ------- | ------ |
| 0 | timestamp | integer (unix seconds) |
| 1 | total_input_tokens | integer |
| 2 | total_output_tokens | integer |
| 3 | current_input_tokens | integer |
| 4 | current_output_tokens | integer |
| 5 | cache_creation | integer |
| 6 | cache_read | integer |
| 7 | cost_usd | float |
| 8 | lines_added | integer |
| 9 | lines_removed | integer |
| 10 | session_id | string |
| 11 | model_id | string |
| 12 | workspace_project_dir | string |
| 13 | context_window_size | integer |

#### Scenario: New-format line has exactly 14 fields

- **WHEN** a writer implementation serializes a state entry in the new format
- **THEN** the resulting line SHALL contain exactly 14 comma-separated values in the order specified above

#### Scenario: Legacy 2-field format is still parseable

- **WHEN** the reader encounters a line with exactly 2 comma-separated values
- **THEN** it SHALL parse field 0 as `timestamp` and field 1 as `total_input_tokens`, defaulting all other fields to zero/empty

### Requirement: ARCHITECTURE.md accurately describes state file format

The `docs/ARCHITECTURE.md` file SHALL NOT describe state file lines as JSON records. It SHALL accurately describe them as CSV format and cross-reference `docs/CSV_FORMAT.md` for the full specification.

#### Scenario: ARCHITECTURE.md references CSV format

- **WHEN** a developer reads the state file section of `docs/ARCHITECTURE.md`
- **THEN** the description SHALL state that each line is a CSV record (not JSON) and SHALL reference `docs/CSV_FORMAT.md` for field details
