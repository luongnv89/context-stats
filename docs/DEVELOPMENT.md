# Development Guide

## Prerequisites

- **Git** - Version control
- **Python 3.9+** - For Python package and testing
- **Bats** - Bash Automated Testing System (optional, for bash tests)
- **pre-commit** - Git hook framework (optional, for automated code quality)

## Setup

```bash
# Clone the repository
git clone https://github.com/luongnv89/cc-context-stats.git
cd cc-context-stats

# Python setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
pip install -e ".[dev]"

# Install pre-commit hooks (optional but recommended)
pre-commit install
```

## Project Layout

```
cc-context-stats/
├── src/claude_statusline/    # Python package source
│   ├── cli/                  #   CLI entry points (statusline, context-stats)
│   ├── core/                 #   Config, state, git, colors
│   ├── formatters/           #   Token, time, layout formatting
│   ├── graphs/               #   ASCII graph rendering
│   └── ui/                   #   Icons, waiting animation
├── scripts/                  # Standalone scripts
│   ├── statusline.py         #   Python standalone statusline
│   └── context-stats.sh      #   Bash context-stats CLI
├── tests/
│   ├── bash/                 # Bats tests (install/check scripts)
│   └── python/               # Pytest tests
├── config/                   # Configuration examples
├── docs/                     # Documentation
├── .github/workflows/        # CI/CD (ci.yml, release.yml)
└── pyproject.toml            # Python build config (hatchling)
```

## Running Tests

```bash
# Python tests
source venv/bin/activate
pytest tests/python/ -v

# Bash integration tests (install/check scripts)
bats tests/bash/test_check_install.bats tests/bash/test_context_stats_subcommands.bats tests/bash/test_e2e_install.bats tests/bash/test_install.bats

# All tests
pytest && bats tests/bash/test_check_install.bats tests/bash/test_context_stats_subcommands.bats tests/bash/test_e2e_install.bats tests/bash/test_install.bats
```

### Coverage Reports

```bash
# Python coverage
pytest tests/python/ -v --cov=scripts --cov-report=html
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

# Inspect state content (14 CSV fields per line)
cat ~/.claude/statusline/statusline.<session_id>.state

# Watch state file updates in real-time
watch -n 1 'tail -5 ~/.claude/statusline/statusline.*.state'
```

### Verbose testing

```bash
# Python with verbose output
pytest tests/python/ -v -s

# Bats with verbose output
bats --verbose-run tests/bash/test_check_install.bats
```
