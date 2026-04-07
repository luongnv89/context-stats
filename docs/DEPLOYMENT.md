# Deployment

## Distribution Channels

cc-context-stats is distributed through two channels:

| Channel      | Package Name      | Command                              |
| ------------ | ----------------- | ------------------------------------ |
| Shell script | N/A               | `curl -fsSL .../install.sh \| bash`  |
| PyPI         | `cc-context-stats`| `pip install cc-context-stats`       |

The pip install provides the `claude-statusline` and `context-stats` CLI commands.

## Publishing to PyPI

```bash
# Ensure clean build
rm -rf dist/ build/

# Build
python -m build

# Check package
twine check dist/*

# Upload to PyPI
twine upload dist/*
```

## Release Workflow

The project uses GitHub Actions for automated releases (`.github/workflows/release.yml`):

1. Update versions in all locations (see Version Management below)
2. Update `CHANGELOG.md` with the new version entry
3. Create and push a version tag: `git tag v1.x.x && git push --tags`
4. The release workflow automatically:
   - Runs the full test suite (Python and Bash)
   - Builds the Python package
   - Creates a GitHub Release with release notes

CI is also run on every push and PR via `.github/workflows/ci.yml`.

## Version Management

Versions must be updated in sync across these files:

| File | Field |
| --- | --- |
| `pyproject.toml` | `[project] version` |
| `src/claude_statusline/__init__.py` | `__version__` |
| `CHANGELOG.md` | New version entry |
| `RELEASE_NOTES.md` | Current release notes |

## Install Script

The `install.sh` script is fetched directly from the `main` branch on GitHub. Changes to the installer take effect immediately for new users running the curl one-liner.

The installer embeds the current version and git commit hash into the installed scripts, preventing version drift between the repository and installed copies.
