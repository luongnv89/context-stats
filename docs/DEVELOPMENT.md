# Development Guide

## Prerequisites

- **Git** - Version control
- **jq** - JSON processor (for bash scripts)
- **Python 3.9+** - For Python package and testing
- **Node.js 18+** - For Node.js script and testing
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

# Node.js setup
npm install

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
├── scripts/                  # Standalone scripts (sh/py/js)
│   ├── statusline-full.sh    #   Full-featured bash statusline
│   ├── statusline-git.sh     #   Git-focused bash variant
│   ├── statusline-minimal.sh #   Minimal bash variant
│   ├── statusline.py         #   Python standalone statusline
│   ├── statusline.js         #   Node.js standalone statusline
│   └── context-stats.sh      #   Bash context-stats CLI
├── tests/
│   ├── bash/                 # Bats tests
│   ├── python/               # Pytest tests
│   └── node/                 # Jest tests
├── config/                   # Configuration examples
├── docs/                     # Documentation
├── .github/workflows/        # CI/CD (ci.yml, release.yml)
├── pyproject.toml            # Python build config (hatchling)
└── package.json              # Node.js config
```

## Running Tests

```bash
# Python tests
source venv/bin/activate
pytest tests/python/ -v

# Node.js tests (Jest)
npm test

# Bash integration tests
bats tests/bash/*.bats

# All tests
pytest && npm test && bats tests/bash/*.bats
```

### Coverage Reports

```bash
# Python coverage
pytest tests/python/ -v --cov=scripts --cov-report=html

# Node.js coverage
npm run test:coverage
```

## Linting & Formatting

```bash
# Run all checks via pre-commit
pre-commit run --all-files

# Individual tools
ruff check src/ scripts/statusline.py            # Python lint
ruff format src/ scripts/statusline.py           # Python format
npx eslint scripts/statusline.js                 # JavaScript lint
npx prettier --write scripts/statusline.js       # JavaScript format
shellcheck scripts/*.sh install.sh               # Bash lint
```

## Manual Testing

```bash
# Test statusline scripts with mock input
echo '{"model":{"display_name":"Test"},"cwd":"/test","session_id":"abc123","context":{"tokens_remaining":64000,"context_window":200000}}' | python3 scripts/statusline.py

echo '{"model":{"display_name":"Test"}}' | node scripts/statusline.js

echo '{"model":{"display_name":"Test"}}' | bash scripts/statusline-full.sh
```

## Building

```bash
# Python package
python -m build

# Verify package
twine check dist/*

# npm dry run
npm pack --dry-run
```

## Cross-Script Consistency

All three implementations (bash, Python, Node.js) must produce identical output for the same input. When modifying status line behavior:

1. Update all three script variants
2. Run integration tests to verify parity
3. Test on multiple platforms if possible

The delta parity tests (`tests/bash/`) verify that Python and Node.js produce identical deltas for the same CSV state data.

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

# Node.js with verbose output
npx jest --verbose

# Bats with verbose output
bats --verbose-run tests/bash/*.bats
```
