## ADDED Requirements

### Requirement: Stdout parity across all shared fixtures

The parity test SHALL feed every JSON file in `tests/fixtures/json/*.json` to both `scripts/statusline.py` and `scripts/statusline.js`, strip ANSI escape codes from both outputs, and assert that the cleaned stdout strings are identical.

#### Scenario: Matching stdout for full input

- **WHEN** `tests/fixtures/json/valid_full.json` is piped to both scripts with `COLUMNS=120`
- **THEN** the ANSI-stripped stdout from Python and Node.js MUST be identical

#### Scenario: Matching stdout for minimal input

- **WHEN** `tests/fixtures/json/valid_minimal.json` is piped to both scripts with `COLUMNS=120`
- **THEN** the ANSI-stripped stdout from Python and Node.js MUST be identical

#### Scenario: Matching stdout for high usage input

- **WHEN** `tests/fixtures/json/high_usage.json` is piped to both scripts with `COLUMNS=120`
- **THEN** the ANSI-stripped stdout from Python and Node.js MUST be identical

#### Scenario: New fixtures automatically included

- **WHEN** a new JSON file is added to `tests/fixtures/json/`
- **THEN** the parity test MUST include it without any test code changes (via glob)

### Requirement: CSV state file parity across all shared fixtures

The parity test SHALL compare the CSV state lines written by both scripts for each fixture and assert that all non-timestamp fields (indices 1–13) are identical.

#### Scenario: Matching CSV fields for full input

- **WHEN** `tests/fixtures/json/valid_full.json` is piped to both scripts with an isolated `$HOME`
- **THEN** the CSV state lines MUST have identical values for fields 1 through 13 (total_input_tokens through context_window_size)

#### Scenario: Timestamp tolerance

- **WHEN** both scripts process the same fixture sequentially
- **THEN** the timestamp field (index 0) MAY differ by at most 2 seconds

#### Scenario: Matching field count

- **WHEN** both scripts write a CSV state line
- **THEN** both lines MUST have exactly 14 comma-separated fields

### Requirement: Deterministic test environment

The parity test SHALL normalize all environment-dependent variables so that output differences reflect only implementation drift, not environmental variance.

#### Scenario: Terminal width normalization

- **WHEN** the parity test runs
- **THEN** `COLUMNS` MUST be set to `120` for both script invocations

#### Scenario: State file isolation

- **WHEN** the parity test runs
- **THEN** `$HOME` MUST point to a temporary directory so state files do not pollute the user's real `~/.claude/statusline/`

#### Scenario: Git info suppression

- **WHEN** the parity test runs
- **THEN** the working directory MUST NOT be inside a git repository, so both scripts omit the git segment

#### Scenario: Cleanup after test

- **WHEN** the parity test completes (pass or fail)
- **THEN** the temporary `$HOME` directory MUST be removed

### Requirement: CI integration

The parity test MUST run automatically in the GitHub Actions CI pipeline on every push to `main` and every pull request targeting `main`.

#### Scenario: CI job runs after individual test suites pass

- **WHEN** both `python-test` and `node-test` CI jobs succeed
- **THEN** a `parity-test` job SHALL execute `bats tests/bash/test_parity.bats`

#### Scenario: CI job has both runtimes available

- **WHEN** the `parity-test` CI job runs
- **THEN** both Python 3.11 and Node.js 20 MUST be installed on the runner

#### Scenario: CI runs on multiple platforms

- **WHEN** the `parity-test` CI job runs
- **THEN** it SHALL execute on both `ubuntu-latest` and `macos-latest`

#### Scenario: Parity failure blocks merge

- **WHEN** the parity test fails
- **THEN** the `ci-success` gate job MUST also fail, blocking PR merge
