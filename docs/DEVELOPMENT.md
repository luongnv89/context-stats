# Development Guide

## Prerequisites

- **Git** - Version control
- **Python 3.10+** - For Python package and testing
- **pre-commit** - Git hook framework (optional, for automated code quality)

## Agent-Runnable Setup Notes

The sequence below is self-contained: run it top to bottom in a fresh clone and every command works as written.

```bash
# 1. Create and activate a Python 3 virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install development tools (pytest, pytest-cov, ruff, mypy, pre-commit),
#    held to the pinned versions in requirements-dev.constraints.txt
pip install -r requirements-dev.txt -c requirements-dev.constraints.txt

# 3. Install the package itself in editable mode
pip install -e .

# 4. Recorded test command (-p no:cacheprovider disables the cache plugin,
#    so test runs never write .pytest_cache/)
pytest tests/python/ -q -p no:cacheprovider

# 5. Coverage report (measures src/claude_statusline per [tool.coverage.run])
pytest tests/python/ -q -p no:cacheprovider --cov=claude_statusline --cov-report=term

# 6. Bootstrap pre-commit hooks into .git/hooks
pre-commit install
```

One-liner equivalent of steps 1 and 4 once the environment exists:

```bash
source venv/bin/activate && pytest tests/python/ -q -p no:cacheprovider
```

### Editable-install version skew

If the version reported by `pip show context-stats` is older than `version` in `pyproject.toml` (for example a venv still holding **1.24.2** while `pyproject.toml` says **1.25.0**), the editable-install metadata is stale. Re-running the editable install clears it:

```bash
pip install -e .
```

## Setup

```bash
# Clone the repository
git clone https://github.com/luongnv89/context-stats.git
cd context-stats

# Python setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt -c requirements-dev.constraints.txt
pip install -e ".[dev]"

# Install pre-commit hooks (optional but recommended)
pre-commit install
```

### Regenerating the dev-dependency constraints file

`requirements-dev.constraints.txt` pins every dev requirement (and its transitive dependencies) to exact versions so local installs and CI are reproducible; it is consumed via `pip install -r requirements-dev.txt -c requirements-dev.constraints.txt` in every CI job that installs dev dependencies (`python-lint`, `python-test`, and the release workflow's test job). To regenerate it after editing `requirements-dev.txt`, resolve at the **Python 3.10 floor** — the oldest version CI supports — so the pins stay installable across the whole 3.10–3.14 matrix: run `pip download --dest /tmp/wheels --python-version 3.10 --only-binary=:all: -r requirements-dev.txt`, read the exact resolved versions from the downloaded wheel filenames, and write them into the constraints file as `name==version` lines (canonical PyPI names, alphabetically sorted).

Then verify before committing: re-run that same download command with `-c requirements-dev.constraints.txt` for each matrix Python (`3.10`, `3.11`, `3.12`, `3.13`, `3.14`) — all five must resolve without conflicts — and run the recorded test command in a clean venv installed with the constraints.

### Security auditing

The locked dev environment is scanned for known vulnerabilities with `pip-audit` (F-DEP-008). The scanner itself is pinned in `requirements-dev.constraints.txt` like every other dev dependency. Run it locally from an activated venv:

```bash
pip-audit -r requirements-dev.constraints.txt --progress-spinner off
# or, equivalently, with the ticketed exceptions applied:
bash scripts/pip-audit-locked.sh
```

CI runs the same audit on every push/PR (`dependency-scan` job in `.github/workflows/ci.yml`) and weekly ([`.github/workflows/security-audit.yml`](../.github/workflows/security-audit.yml)). The gate fails on **any** known advisory — stricter than the High/Critical requirement.

**Exception policy:** an advisory may only be silenced with a filed ticket. Add one `--ignore-vuln <ID>` line per advisory to `scripts/pip-audit-locked.sh`, reference the ticket in that script's header comment, and note it in `requirements-dev.constraints.txt`. The exceptions tracked in [#161](https://github.com/luongnv89/context-stats/issues/161) — every fix version required Python >= 3.10 directly, or conflicted across the CI matrix with the old Python 3.9-floor pins — became actionable when the minimum supported Python rose to 3.10 ([ADR 0001](adr/python-support-floor.md), #133/#134): the affected pins were bumped and their flags deleted as part of that task. When a **new** advisory appears: first try bumping the pin within what resolves at the 3.10 floor; only if no fix installs, file a ticket and add the flag.

## Project Layout

```
context-stats/
├── src/claude_statusline/    # Python package source
│   ├── cli/                  #   CLI entry points (statusline, context-stats)
│   ├── core/                 #   Config, state, git, colors
│   ├── formatters/           #   Token, time, layout formatting
│   ├── graphs/               #   ASCII graph rendering
│   └── ui/                   #   Icons, waiting animation
├── scripts/                  # Standalone scripts
│   └── statusline.py         #   Python standalone statusline
├── tests/
│   └── python/               # Pytest tests
├── examples/                 # Configuration examples
├── docs/                     # Documentation
├── .github/workflows/        # CI/CD (ci.yml, release.yml)
└── pyproject.toml            # Python build config (hatchling)
```

## Running Tests

```bash
# Command of record
source venv/bin/activate
pytest tests/python/ -q -p no:cacheprovider
```

### Coverage Reports

```bash
# Python coverage (measures src/claude_statusline per [tool.coverage.run])
pytest tests/python/ -v --cov=claude_statusline --cov-report=html
```

## Linting & Formatting

```bash
# Run all checks via pre-commit
pre-commit run --all-files

# Individual tools
ruff check src/ scripts/statusline.py            # Python lint
ruff format src/ scripts/statusline.py           # Python format
shellcheck scripts/*.sh install.sh               # Bash lint
```

## Manual Testing

```bash
# Test statusline script with mock input
echo '{"model":{"display_name":"Test"},"cwd":"/test","session_id":"abc123","context":{"tokens_remaining":64000,"context_window":200000}}' | python3 scripts/statusline.py
```

## Building

```bash
# Python package
python -m build

# Verify package
twine check dist/*
```

## Consistency: Package vs Standalone Script

The standalone `scripts/statusline.py` duplicates core logic from the `src/` package so it can run without installation. When modifying status line behavior:

1. Update both `scripts/statusline.py` and the corresponding `src/` module
2. Run Python tests to verify correctness

## Debugging

### State files

```bash
# View current state files
ls -la ~/.claude/statusline/statusline.*.state

# Inspect state content (15 CSV fields per line)
cat ~/.claude/statusline/statusline.<session_id>.state

# Watch state file updates in real-time
watch -n 1 'tail -5 ~/.claude/statusline/statusline.*.state'
```

### Verbose testing

```bash
# Python with verbose output
pytest tests/python/ -v -s
```
