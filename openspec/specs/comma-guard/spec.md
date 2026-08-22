## ADDED Requirements

### Requirement: Commas in workspace_project_dir are replaced before CSV serialization

All writer implementations (Python, Node.js, bash) SHALL replace comma characters (`,`) in the `workspace_project_dir` value with underscore characters (`_`) before writing the CSV line.

#### Scenario: Path without commas is unchanged

- **WHEN** `workspace_project_dir` is `/home/user/my-project`
- **THEN** the value written to the CSV field at index 12 SHALL be `/home/user/my-project`

#### Scenario: Path with commas has commas replaced

- **WHEN** `workspace_project_dir` is `/home/user/my,project,dir`
- **THEN** the value written to the CSV field at index 12 SHALL be `/home/user/my_project_dir`

#### Scenario: Empty path remains empty

- **WHEN** `workspace_project_dir` is an empty string
- **THEN** the value written to the CSV field at index 12 SHALL be an empty string

### Requirement: Comma guard is consistent across all writer implementations

The comma replacement logic SHALL produce identical output for the same input across all 5 writer implementations: Python (`state.py`), Node.js (`statusline.js`), bash (`statusline-full.sh`, `statusline-mid.sh`, `statusline-min.sh`).

#### Scenario: Python and Node.js produce identical output for path with commas

- **WHEN** both Python and Node.js writers receive the same JSON input containing a `workspace_project_dir` with commas
- **THEN** the CSV lines written by both implementations SHALL be byte-identical

#### Scenario: Bash writers apply the same replacement

- **WHEN** a bash writer receives a `workspace_project_dir` value containing commas
- **THEN** the comma replacement SHALL use the same rule (`,` → `_`) as Python and Node.js

### Requirement: Comma guard is applied at serialization time

The comma replacement SHALL be applied during CSV line construction (write path), not during CSV line parsing (read path). The parser SHALL NOT need modification.

#### Scenario: Parser handles sanitized paths without changes

- **WHEN** the reader parses a CSV line where `workspace_project_dir` has been sanitized (commas replaced with underscores)
- **THEN** the existing `split(",")` parsing logic SHALL correctly extract all 14 fields without modification
