# Contributing to context-stats

Thank you for your interest in contributing to context-stats! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- **Git** - Version control
- **Python 3.10+** - For the package and test suite
- **pre-commit** - Git hook framework (optional, for automated code quality)

### Installing Dependencies

```bash
# Clone the repository
git clone https://github.com/luongnv89/context-stats.git
cd context-stats

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install development tools (pytest, pytest-cov, ruff, mypy, pre-commit),
# held to the pinned versions in requirements-dev.constraints.txt
pip install -r requirements-dev.txt -c requirements-dev.constraints.txt

# Install the package itself in editable mode
pip install -e .

# Install pre-commit hooks
pre-commit install
```

## Project Structure

```text
context-stats/
├── src/claude_statusline/      # Installable Python package
│   ├── cli/                    #   Entry points (statusline, context-stats, ...)
│   ├── core/                   #   Config, state, git, colors
│   ├── formatters/             #   Token, time, layout formatting
│   ├── graphs/                 #   ASCII rendering, MI/zones, statistics
│   └── ui/                     #   Icons, waiting animation
├── scripts/                    # Standalone scripts (no-install usage)
│   ├── statusline.py           #   Python standalone statusline
│   └── _statusline_shared.py   #   Vendored shared core for the script
├── examples/                   # Configuration examples (statusline.conf)
├── config/                     # Claude Code settings examples
├── tests/python/               # Pytest suite
├── docs/                       # Documentation
├── .github/workflows/          # CI/CD workflows
└── pyproject.toml              # Python build config (hatchling)
```

## Running Tests

### Command of Record

```bash
source venv/bin/activate && pytest tests/python/ -q -p no:cacheprovider
```

`-p no:cacheprovider` disables the cache plugin so test runs never write `.pytest_cache/`.

### Coverage

```bash
# Measures src/claude_statusline per [tool.coverage.run]; the 94% floor is
# enforced by --cov-fail-under=94 in [tool.pytest.ini_options] addopts
pytest tests/python/ -q -p no:cacheprovider --cov=claude_statusline --cov-report=term
```

## Code Quality

### Linting

```bash
# Run all hooks (formatting, whitespace, shellcheck, markdownlint, e2e smoke)
pre-commit run --all-files

# Individual linters — same commands CI runs
ruff check .                  # Python lint
ruff format --check .         # Python format check
mypy src scripts              # Type checking
```

### Formatting

```bash
# Auto-format Python
ruff format .

# Check formatting without modifying
ruff format --check .
```

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feat/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Changes

- Follow the existing code style
- Add tests for new functionality
- Update documentation if needed
- Ensure both implementations produce identical output (see below)

### 3. Test Your Changes

```bash
# Run pre-commit hooks
pre-commit run --all-files

# Run the test suite (command of record)
pytest tests/python/ -q -p no:cacheprovider

# Test the standalone script manually
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
git push origin feat/your-feature-name
```

Then create a Pull Request on GitHub.

## Implementation Guidelines

### Cross-Implementation Consistency

The package (`src/claude_statusline/`) and the standalone script (`scripts/statusline.py`) must render identical output. When making changes:

1. Update `scripts/statusline.py` and the corresponding `src/` module in sync (see CLAUDE.md for sync points)
2. Run the parity suite (`tests/python/test_parity.py`, part of the command of record) to verify correctness
3. Test on multiple platforms if possible

### Output Format

The status line assembles these segments in priority order:

```text
my-project | main [3] | #42 | 64,000 free (32.0%)·Code·ᗤ | MI:0.918 | 42.5 tok/s | +2,500 | $0.42 | Opus 4.6·high | abc-123
```

Components:

- `my-project` - Current directory name (cyan)
- `main [3]` - Git branch name and uncommitted changes count
- `#42` - PR number for the current branch (via `gh`; `show_pr`)
- `64,000 free (32.0%)·Code·ᗤ` - Available tokens, utilization, context zone, pacman icon (one atomic group)
- `MI:0.918` - Model Intelligence score (`show_mi`)
- `42.5 tok/s` - Model throughput (`show_tps`)
- `+2,500` - Token delta since last refresh (`show_delta`)
- `$0.42` - Cumulative session cost (`show_cost`)
- `Opus 4.6·high` - Model name with reasoning effort suffix (`show_effort`)
- `abc-123` - Session ID (`show_session`)

Every segment is toggleable via `~/.claude/statusline.conf` — see [docs/configuration.md](docs/configuration.md) for keys and defaults.

On a narrow terminal the statusline wraps onto additional lines instead of dropping elements; see README ("Level 1: Live Stats") for the reflow behavior.

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

Prefer named colors or `#rrggbb` hex values through the config system over raw literals — see [docs/configuration.md](docs/configuration.md#custom-colors).

## Questions?

If you have questions, feel free to:

- Open an issue on GitHub
- Check existing issues for similar questions

Thank you for contributing!
