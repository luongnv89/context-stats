# Contributing to Claude Code Status Line

Thank you for your interest in contributing to Claude Code Status Line! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- **Git** - Version control
- **jq** - JSON processor (for bash scripts)
- **Python 3.9+** - For Python script and testing
- **Bats** - Bash Automated Testing System

### Installing Dependencies

#### macOS

```bash
# Install system dependencies
brew install jq bats-core

# Clone the repository
git clone https://github.com/luongnv89/cc-context-stats.git
cd cc-context-stats

# Install Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install
```

#### Linux (Ubuntu/Debian)

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y jq bats

# Clone the repository
git clone https://github.com/luongnv89/cc-context-stats.git
cd cc-context-stats

# Install Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install
```

## Project Structure

```text
cc-context-stats/
├── scripts/                    # Main scripts
│   └── statusline.py           # Python standalone statusline
├── src/                        # Installable Python package
├── config/                     # Configuration examples
├── tests/                      # Test suites
│   ├── fixtures/json/          # Test fixtures
│   ├── bash/                   # Bats tests
│   └── python/                 # Pytest tests
├── .github/workflows/          # CI/CD workflows
├── install.sh                  # Installation script
└── README.md                   # Documentation
```

## Running Tests

### All Tests

```bash
# Run all tests
pytest && bats tests/bash/test_check_install.bats tests/bash/test_context_stats_subcommands.bats tests/bash/test_e2e_install.bats tests/bash/test_install.bats
```

### Individual Test Suites

```bash
# Bash tests (requires bats)
bats tests/bash/*.bats

# Python tests
pytest tests/python/ -v

# Python tests with coverage
pytest tests/python/ -v --cov=scripts --cov-report=html
```

## Code Quality

### Linting

```bash
# Run all linters
pre-commit run --all-files

# Individual linters
ruff check scripts/statusline.py          # Python
shellcheck install.sh                     # Bash
```

### Formatting

```bash
# Auto-format Python
ruff format scripts/statusline.py

# Check formatting without modifying
ruff format --check scripts/statusline.py
```

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Changes

- Follow the existing code style
- Add tests for new functionality
- Update documentation if needed
- Ensure all scripts produce consistent output

### 3. Test Your Changes

```bash
# Run pre-commit hooks
pre-commit run --all-files

# Run all tests
bats tests/bash/test_check_install.bats tests/bash/test_context_stats_subcommands.bats tests/bash/test_e2e_install.bats tests/bash/test_install.bats
pytest tests/python/ -v

# Test scripts manually
echo '{"model":{"display_name":"Test"}}' | python3 ./scripts/statusline.py
```

### 4. Commit Your Changes

Use conventional commit messages:

```bash
git commit -m "feat: add new feature description"
git commit -m "fix: fix bug description"
git commit -m "docs: update documentation"
git commit -m "test: add tests for feature"
git commit -m "refactor: refactor code description"
```

### 5. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

## Script Guidelines

### Cross-Script Consistency

The Python implementation is the sole implementation. When making changes:

1. Update `scripts/statusline.py` and the corresponding `src/` module in sync (see CLAUDE.md for sync points)
2. Run Python tests to verify correctness
3. Test on multiple platforms if possible

### Output Format

The status line output should follow this format:

```text
[Model] directory | branch [changes] | XXk free (XX%) [AC:XXk]
```

Components:

- `[Model]` - AI model name (dim)
- `directory` - Current directory name (blue)
- `branch` - Git branch name (magenta)
- `[changes]` - Uncommitted changes count (cyan)
- `XXk free (XX%)` - Available context tokens (green/yellow/red)
- `[AC:XXk]` - Autocompact buffer (dim)

### Color Codes

Use ANSI color codes consistently:

- Blue: `\033[0;34m`
- Magenta: `\033[0;35m`
- Cyan: `\033[0;36m`
- Green: `\033[0;32m`
- Yellow: `\033[0;33m`
- Red: `\033[0;31m`
- Dim: `\033[2m`
- Reset: `\033[0m`

## Questions?

If you have questions, feel free to:

- Open an issue on GitHub
- Check existing issues for similar questions

Thank you for contributing!
