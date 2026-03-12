# Deployment

## Distribution Channels

cc-context-stats is distributed through three channels:

| Channel      | Package Name      | Command                              |
| ------------ | ----------------- | ------------------------------------ |
| Shell script | N/A               | `curl -fsSL .../install.sh \| bash`  |
| PyPI         | `cc-context-stats`| `pip install cc-context-stats`       |
| npm          | `cc-context-stats`| `npm install -g cc-context-stats`    |

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

## Publishing to npm

```bash
# Verify package.json
npm pack --dry-run

# Publish
npm publish
```

## Release Workflow

The project uses GitHub Actions for automated releases (`.github/workflows/release.yml`):

1. Create and push a version tag: `git tag v1.x.x && git push --tags`
2. The release workflow automatically:
   - Runs the full test suite
   - Builds Python and npm packages
   - Creates a GitHub Release with release notes

## Version Management

Versions must be updated in sync across:

- `pyproject.toml` - `[project] version`
- `package.json` - `version`
- `CHANGELOG.md` - New version entry
- `RELEASE_NOTES.md` - Current release notes

## Install Script

The `install.sh` script is fetched directly from the `main` branch on GitHub. Changes to the installer take effect immediately for new users running the curl one-liner.
